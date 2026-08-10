/* MFF Yahoo Helper — draft-mode.js (v0.5.0)
 *
 * The Yahoo DRAFT assistant. Standalone content script — the season sidebar
 * (sidebar.js) is untouched; this activates only in the draft client
 * (/draftclient/f1/<leagueId>/<teamId>).
 *
 * v0.5.0: the rec engine is now a 1:1 port of the ESPN helper's (v0.17.9) —
 * the same scoring pipeline running on the same players.json board:
 *  - composite score: board position + format VOR + tier boosts + cliffs
 *  - draft-capital need model (pickValue / capitalShares / capitalDeficits)
 *  - positional QUALITY fill (QB3 in rd 6 still closes QB; WR2+WR5 ≠ done)
 *  - depletion-need schedule + quality-aware cycles + ahead-deletes-the-nag
 *  - early RB2 window (rounds 3-5 with <2 RB)
 *  - elite QB/TE closes the position + abundance kill w/ surplus multiplier
 *  - ADP scored ONLY as "likely there at your next pick", with round-based
 *    ADP-trust decay; STEAL/Value/Reach/Stretch tags render but don't vote
 *  - leapfrog guard w/ roster-penalty exemption
 *  - roster lock: forced K/DST endgame rebuilds the board from those pools
 *
 * Data plumbing (unchanged from v0.4.x, decoded from Jack's real 2026-08-10
 * draft):
 *  - League data: pub-api.fantasysports.yahoo.com/fantasy/v3 settings/teams/
 *    players (cookie-auth GETs, CORS-enabled for this origin).
 *  - Pick feed: PASSIVE. probe.js (MAIN world) wraps the draft client's own
 *    WebSocket and re-dispatches every frame as an 'mff-yahoo-probe' event.
 *    Frames (pipe-delim): R| snake order · P| full replay · 0| live pick ·
 *    D| on the clock · C| clock tick. Missed early frames backfill from the
 *    probe's chrome.storage log.
 *  - Jack's board: data/players.json (same schema as the ESPN extension) —
 *    engine runs on board entries; the Yahoo pool only maps pids -> board.
 */
(function () {
  'use strict';
  if (window.__mffYahooDraftLoaded) return;
  window.__mffYahooDraftLoaded = true;

  const MOCK = window.MFF_DRAFT_MOCK || null;

  function urlParts() {
    if (MOCK) return { leagueId: MOCK.leagueId, teamId: MOCK.teamId };
    const m = location.pathname.match(/^\/draftclient\/f1\/(\d+)\/(\d+)/);
    return m ? { leagueId: m[1], teamId: parseInt(m[2], 10) } : null;
  }
  const ids = urlParts();
  if (!ids) return;

  const API = 'https://pub-api.fantasysports.yahoo.com/fantasy/v3/';

  const st = {
    leagueId: ids.leagueId,
    myTeamId: ids.teamId,
    leagueName: '',
    slots: { teams: 10, rounds: 15, qb: 1, rb: 2, wr: 2, te: 1, flex: 1, sf: 0, k: 1, dst: 1, bench: 6 },
    scoringLabel: '',
    scoringVals: { recPts: 0.5, passTd: 4 },
    pool: Object.create(null),     // yahooPlayerId -> rec
    board: [],                     // players.json entries (engine substrate)
    order: [],                     // teamId per overall pick (from R frame)
    picks: Object.create(null),    // pickNo -> {pid, tid, slot}
    taken: new Set(),              // yahoo pids drafted
    draftedKeys: new Set(),        // board keys drafted (derived)
    manualDrafted: new Set(),      // board keys marked drafted by hand
    manualMine: new Set(),         // board keys marked as my pick by hand
    myRoster: [],                  // [{p, name, pos, pickNo}]
    currentPick: 0,
    onClockTeam: 0,
    clock: null,
    teams: Object.create(null),    // teamId -> name
    mode: 're_1qb',
    rankSource: 'jack',
    tab: 'recs',
    posFilter: 'ALL',
    sortVor: false,
    searchQ: '',
    ready: false,
  };
  // Back-compat aliases for the harness / console (numTeams was v0.4.x).
  Object.defineProperty(st, 'numTeams', {
    get() { return this.slots.teams; },
    set(v) { this.slots.teams = v; },
  });

  // ---------- name matching (players.json board <-> yahoo pool) ----------
  function norm(n) {
    return String(n || '').toLowerCase()
      .replace(/\s+(jr\.?|sr\.?|ii|iii|iv|v)$/i, '')
      .replace(/[.\-'\s]/g, '');
  }
  function keyOf(p) { return norm(p.n) + '|' + p.s; }
  const NICK = { kenny: 'kenneth', kenneth: 'kenny', mitch: 'mitchell', mitchell: 'mitch',
    cam: 'cameron', cameron: 'cam', gabe: 'gabriel', gabriel: 'gabe',
    marquise: 'hollywood', hollywood: 'marquise', nate: 'nathaniel', nathaniel: 'nate',
    josh: 'joshua', joshua: 'josh' };
  let boardByKey = Object.create(null);
  let dstByTeam = Object.create(null);
  function indexBoard() {
    boardByKey = Object.create(null);
    dstByTeam = Object.create(null);
    for (const b of st.board) {
      if (b.s === 'DST') { if (b.sTm) dstByTeam[b.sTm.toUpperCase()] = b; }
      boardByKey[keyOf(b)] = b;
    }
  }
  function fixAbbr(a) {
    a = String(a || '').toUpperCase();
    return a === 'WAS' ? 'WSH' : a === 'JAC' ? 'JAX' : a;
  }
  function boardFor(p) {
    if (p.pos === 'DEF') return dstByTeam[fixAbbr(p.team)] || null;
    let b = boardByKey[norm(p.name) + '|' + p.pos];
    if (!b) {
      const parts = p.name.split(' ');
      const alt = NICK[parts[0].toLowerCase()];
      if (alt) b = boardByKey[norm([alt].concat(parts.slice(1)).join(' ')) + '|' + p.pos];
    }
    return b || null;
  }
  // Reverse: board entry -> yahoo pool rec (for bye/inj/Y!ADP/proj display).
  let poolByBoard = new Map();
  function linkBoard() {
    poolByBoard = new Map();
    for (const pid in st.pool) {
      const rec = st.pool[pid];
      rec.b = boardFor(rec);
      if (rec.b && !poolByBoard.has(rec.b)) poolByBoard.set(rec.b, rec);
    }
  }

  // ---------- data loading ----------
  function getJson(url) {
    if (MOCK) {
      if (url.indexOf('/settings/') >= 0) return Promise.resolve(MOCK.settings);
      if (url.indexOf('/teams/') >= 0) return Promise.resolve(MOCK.teams);
      if (url.indexOf('/players/') >= 0) return Promise.resolve(MOCK.players);
    }
    return fetch(url, { credentials: 'include' }).then((r) => {
      if (!r.ok) throw new Error('HTTP ' + r.status + ' on ' + url);
      return r.json();
    });
  }
  function loadBoard() {
    if (MOCK) return Promise.resolve(MOCK.playersJson);
    return fetch(chrome.runtime.getURL('data/players.json')).then((r) => r.json());
  }

  function applySettings(svc) {
    st.leagueName = svc.name || ('League ' + st.leagueId);
    const sl = st.slots;
    sl.teams = parseInt(svc.num_teams, 10) || 10;
    sl.qb = sl.rb = sl.wr = sl.te = sl.flex = sl.sf = sl.k = sl.dst = sl.bench = 0;
    const rp = (svc.settings && svc.settings.roster_positions) || [];
    for (const r of rp) {
      const n = parseInt(r.count, 10) || 0;
      switch (r.position) {
        case 'QB': sl.qb += n; break;
        case 'RB': sl.rb += n; break;
        case 'WR': sl.wr += n; break;
        case 'TE': sl.te += n; break;
        case 'K': sl.k += n; break;
        case 'DEF': sl.dst += n; break;
        case 'W/R/T': case 'W/R': case 'W/T': case 'R/T': sl.flex += n; break;
        case 'Q/W/R/T': sl.sf += n; break;
        case 'BN': sl.bench += n; break;
        default: break; // IR, IDP slots — not drafted rounds we model
      }
    }
    syncRounds();
    st.mode = sl.sf > 0 ? 're_sf' : 're_1qb';
    let rec = 0.5, passTd = 4;
    const cats = (svc.settings && svc.settings.stat_categories) || [];
    for (const c of cats) {
      if (c.stat_id === 11) rec = parseFloat(c.stat_modifier) || 0;
      if (c.stat_id === 5) passTd = parseFloat(c.stat_modifier) || 4;
    }
    st.scoringVals = { recPts: rec, passTd };
    st.scoringLabel =
      (rec >= 1 ? 'PPR' : rec > 0 ? '½PPR' : 'STD') +
      (passTd !== 4 ? ' · ' + passTd + 'pt paTD' : '');
  }
  // Total draft rounds: authoritative from the R| snake order once it lands,
  // starters + bench before that.
  function starterSlotCount() {
    const sl = st.slots;
    return sl.qb + sl.rb + sl.wr + sl.te + sl.flex + sl.sf + sl.k + sl.dst;
  }
  function syncRounds() {
    st.slots.rounds = st.order.length
      ? Math.max(1, Math.round(st.order.length / st.slots.teams))
      : starterSlotCount() + st.slots.bench;
  }

  function applyTeams(svc) {
    for (const t of svc.team_list || []) st.teams[t.id] = t.teamname || ('Team ' + t.id);
  }

  function applyPlayers(svc) {
    for (const p of svc.player_list || []) {
      const rec = {
        pid: p.id,
        name: (p.fname + ' ' + p.lname).trim(),
        pos: p.display_pos === 'DEF' ? 'DEF' : (p.primary_pos || p.display_pos || ''),
        team: fixAbbr(p.team_abbr),
        bye: parseInt(p.bye, 10) || 0,
        inj: p.inj || '',
        yAdp: parseFloat(p['average-pick']) || 999,
        orank: parseInt(p.o_rank, 10) || 9999,
        proj: parseFloat(p.projected && p.projected.points) || 0,
        b: null,
      };
      st.pool[rec.pid] = rec;
    }
  }

  // ---------- league-scoring adjustment (identical to the ESPN helper:
  // Clay cPts is full-PPR / 4-pt paTD; shift to THIS league's settings) ----------
  function applyLeagueScoring() {
    const recPts = st.scoringVals.recPts, passTd = st.scoringVals.passTd;
    for (const p of st.board) {
      if (p.cPts == null || !p.cGm) continue;
      const adj = p.cPts + (recPts - 1) * (p.cRec || 0) + (passTd - 4) * (p.cPtd || 0);
      p.szn = Math.round(adj * 10) / 10;
      p.pPg = Math.round((adj / p.cGm) * 10) / 10;
      p.scDelta = Math.round((((recPts - 0.5) * (p.cRec || 0) +
        (passTd - 4) * (p.cPtd || 0)) / p.cGm) * 10) / 10;
    }
  }

  // ---------- pick feed ----------
  function addPick(pickNo, pid, tid, slot) {
    if (st.picks[pickNo]) return;
    st.picks[pickNo] = { pid, tid, slot: slot || '' };
    st.taken.add(pid);
    if (pickNo >= st.currentPick) st.currentPick = pickNo + 1;
  }
  // draftedKeys + myRoster are DERIVED from picks + manual marks, ESPN-style,
  // so backfill-before-board-load and manual fixes all resolve the same way.
  function rebuildFromPicks() {
    st.draftedKeys = new Set();
    st.myRoster = [];
    const nos = Object.keys(st.picks).map(Number).sort((a, b) => a - b);
    for (const no of nos) {
      const pk = st.picks[no];
      const rec = st.pool[pk.pid];
      const p = rec ? rec.b : null;
      if (p) st.draftedKeys.add(keyOf(p));
      if (pk.tid === st.myTeamId) {
        st.myRoster.push({
          p: p || null,
          name: rec ? rec.name : ('#' + pk.pid),
          pos: p ? p.s : (rec ? (rec.pos === 'DEF' ? 'DST' : rec.pos) : '?'),
          pickNo: no,
        });
      }
    }
    for (const k of st.manualDrafted) st.draftedKeys.add(k);
    for (const k of st.manualMine) {
      const p = boardByKey[k];
      if (!p || st.myRoster.some((r) => r.p === p)) continue;
      st.draftedKeys.add(k);
      st.myRoster.push({ p, name: p.n, pos: p.s, pickNo: null, manual: true });
    }
  }
  function handleFrame(raw) {
    const parts = String(raw).split('|');
    const t = parts[0];
    if (t === 'R') {
      st.order = parts.slice(1).map(Number).filter((x) => x > 0);
      if (st.order.length) {
        st.slots.teams = Math.max(st.slots.teams, new Set(st.order.slice(0, 24)).size);
        syncRounds();
      }
    } else if (t === 'P') {
      for (let i = 1; i < parts.length; i++) {
        const m = parts[i].match(/^(\d+)=(\d+),(\d+)/);
        if (m) addPick(parseInt(m[1], 10), parseInt(m[2], 10), parseInt(m[3], 10), '');
      }
      rebuildFromPicks();
      scheduleRender();
    } else if (t === '0' && parts.length >= 4) {
      addPick(parseInt(parts[1], 10), parseInt(parts[2], 10), parseInt(parts[3], 10), parts[4] || '');
      rebuildFromPicks();
      scheduleRender();
    } else if (t === 'D' && parts.length >= 4) {
      st.currentPick = parseInt(parts[1], 10);
      st.onClockTeam = parseInt(parts[2], 10);
      st.clock = parseInt(parts[3], 10);
      scheduleRender();
    } else if (t === 'C') {
      st.clock = parseInt(parts[1], 10);
      renderClock();
    }
  }
  document.addEventListener('mff-yahoo-probe', (e) => {
    try {
      const d = JSON.parse(e.detail);
      if (d.kind === 'ws-msg') handleFrame(d.url);
    } catch (_) {}
  });
  // Backfill frames the probe logged before this script attached (storage
  // keeps the first 600 entries — enough for R + the P replay).
  function backfill() {
    if (MOCK) return Promise.resolve();
    return new Promise((res) => {
      try {
        chrome.storage.local.get(['mff_yahoo_probe'], (cur) => {
          const log = cur && cur.mff_yahoo_probe;
          if (log && Array.isArray(log.urls)) {
            for (const en of log.urls) if (en.kind === 'ws-msg') handleFrame(en.url);
          }
          res();
        });
      } catch (_) { res(); }
    });
  }

  // ---------- pick math ----------
  function takenCount() { return Object.keys(st.picks).length; }
  function nextPickNo() { return Math.max(takenCount() + 1, st.currentPick || 1, 1); }
  function currentRound() {
    return Math.min(st.slots.rounds, Math.ceil(nextPickNo() / st.slots.teams));
  }
  function picksUntilMine() {
    if (!st.order.length) return null;
    const next = nextPickNo();
    for (let p = next; p <= st.order.length; p++) {
      if (st.order[p - 1] === st.myTeamId) return p - next;
    }
    return null;
  }
  // Overall number of my pick AFTER the one I'm currently making — the
  // "will he still be there?" horizon for the leapfrog guard.
  function myNextPickOverall() {
    if (!st.order.length) return null;
    let found = 0;
    for (let p = nextPickNo(); p <= st.order.length; p++) {
      if (st.order[p - 1] === st.myTeamId) {
        found++;
        if (found === 2) return p;
      }
    }
    return null;
  }

  // ---------- modes / rank sources (ESPN helper, redraft modes) ----------
  const MODES = {
    re_1qb: { label: 'Redraft 1QB', src: 'jack', qbFloor: 1 },
    re_sf:  { label: 'Redraft SF',  src: 'jack', qbFloor: 2 },
  };
  const MODE_KEYS = {
    re_sf:  { jack: 'jSf',  fp: 'fpSf', sl: 'slSf', adp: 'sfa', vor: 'vorSf', up: 'upSf' },
    re_1qb: { jack: 'rank', fp: 'fpR',  sl: 'slR',  adp: 'a',   vor: 'vor',   up: 'up'   },
  };
  function modeKeys() { return MODE_KEYS[st.mode] || MODE_KEYS.re_1qb; }
  const SOURCES = {
    jack: { label: "Jack's Rank",  get: (p) => p[modeKeys().jack], desc: false },
    fp:   { label: 'FantasyPros',  get: (p) => p[modeKeys().fp],   desc: false },
    sl:   { label: 'Sleeper Rank', get: (p) => p[modeKeys().sl],   desc: false },
  };

  // ---------- engine substrate (1:1 with espn-extension/sidebar.js) ----------
  function isDrafted(p) {
    return st.draftedKeys.has(keyOf(p)) || st.manualDrafted.has(keyOf(p));
  }
  function availablePlayers() {
    return st.board.filter((p) => !isDrafted(p) && !p.ir);
  }
  // Fall-based ADP tags: a player still on the board past his ADP is FALLING
  // (STEAL/Value); a player whose ADP is well after the current pick would be
  // a market reach — don't reach 20+ picks, you can very likely get him on a
  // later turn (Reach/Stretch).
  function adpTag(p) {
    const adp = p[modeKeys().adp];
    if (adp == null) return null;
    const t = st.slots.teams || 12;
    const diff = adp - nextPickNo(); // +ve = market drafts him later
    if (diff <= -2 * t) return 'STEAL';   // fell 2+ rounds past ADP
    if (diff <= -t) return 'Value';       // fell a full round
    if (diff >= 20) return 'Reach';       // 20+ picks early vs market
    if (diff >= 12) return 'Stretch';     // roughly a round early
    return null;
  }
  function stackInfo(p) {
    if (!p.sTm) return null;
    const mates = st.myRoster.filter((r) => r.p && r.p.sTm === p.sTm);
    if (!mates.length) return null;
    const hasQB = mates.some((r) => r.pos === 'QB');
    const hasCatcher = mates.some((r) => r.pos === 'WR' || r.pos === 'TE');
    const names = mates.map((m) => m.name);
    if (((p.s === 'WR' || p.s === 'TE') && hasQB) || (p.s === 'QB' && hasCatcher)) {
      return { type: 'stack', names };
    }
    return { type: 'team', names };
  }
  function starterProjPPG() {
    const sl = st.slots;
    const pool = st.myRoster
      .filter((r) => r.p && r.p.pPg != null)
      .map((r) => ({ pos: r.pos, ppg: r.p.pPg }))
      .sort((a, b) => b.ppg - a.ppg);
    const used = new Array(pool.length).fill(false);
    let total = 0;
    function take(posSet, n) {
      for (let k = 0; k < (n || 0); k++) {
        const i = pool.findIndex((x, idx) => !used[idx] && posSet.includes(x.pos));
        if (i < 0) return;
        used[i] = true;
        total += pool[i].ppg;
      }
    }
    take(['QB'], sl.qb); take(['RB'], sl.rb);
    take(['WR'], sl.wr); take(['TE'], sl.te);
    take(['RB', 'WR', 'TE'], sl.flex);
    take(['QB', 'RB', 'WR', 'TE'], sl.sf);
    take(['K'], sl.k);
    return Math.round(total * 10) / 10;
  }
  function sortListBySource(list) {
    const src = SOURCES[st.rankSource] || SOURCES.jack;
    return list.slice().sort((a, b) => {
      const va = src.get(a), vb = src.get(b);
      if (va == null && vb == null) return a.rank - b.rank;
      if (va == null) return 1;
      if (vb == null) return -1;
      return src.desc ? vb - va : va - vb;
    });
  }
  function sortedAvailable() {
    let avail = availablePlayers().filter(
      (p) => st.posFilter === 'ALL' || p.s === st.posFilter
    );
    avail = sortListBySource(avail);
    if (st.sortVor) {
      const vk = modeKeys().vor;
      avail.sort((a, b) => {
        const va = a[vk], vb = b[vk];
        if (va == null && vb == null) return 0;
        if (va == null) return 1;
        if (vb == null) return -1;
        return vb - va;
      });
    }
    return avail;
  }
  function rosterCounts() {
    const c = { QB: 0, RB: 0, WR: 0, TE: 0, K: 0, DST: 0 };
    for (const r of st.myRoster) if (c[r.pos] != null) c[r.pos]++;
    return c;
  }
  // Draft-capital-weighted position counts: a round-1 pick "fills" a position
  // far more than a round-9 dart. quality = 1.0 through round 2, declining
  // ~7%/round to a 0.4 floor; manual adds (unknown pick) count 0.7.
  function effRosterCounts() {
    const t = st.slots.teams || 12;
    const c = { QB: 0, RB: 0, WR: 0, TE: 0, K: 0, DST: 0 };
    for (const r of st.myRoster) {
      if (c[r.pos] == null) continue;
      const rd = r.pickNo ? Math.ceil(r.pickNo / t) : null;
      c[r.pos] += rd == null ? 0.7 : Math.max(0.4, Math.min(1, 1.14 - 0.07 * rd));
    }
    return c;
  }
  // Draft-capital VALUE model — see espn-extension/sidebar.js for the full
  // rationale on every block below; this is a verbatim port.
  function pickValue(n) { return 60 * Math.exp(-n / 85) + 4; }
  const CAPITAL_SHARE = {
    sf:  { QB: 0.30, RB: 0.21, WR: 0.33, TE: 0.12 },
    one: { QB: 0.11, RB: 0.28, WR: 0.45, TE: 0.12 },
  };
  function capitalShares() {
    const s = Object.assign({}, CAPITAL_SHARE[st.mode.endsWith('_sf') ? 'sf' : 'one']);
    const sl = st.slots;
    if (sl.rb || sl.wr) {
      const flex = sl.flex || 0;
      s.RB *= ((sl.rb || 2) + 0.45 * flex) / 2.45;
      s.WR *= ((sl.wr || 2) + 0.55 * flex) / 2.55;
      s.TE *= sl.te || 1;
    }
    const rec = st.scoringVals.recPts != null ? st.scoringVals.recPts : 1;
    if (rec >= 0.75) { s.WR *= 1.08; s.RB *= 0.94; }       // full PPR
    else if (rec <= 0.25) { s.RB *= 1.1; s.WR *= 0.92; }    // STD-ish
    const tot = s.QB + s.RB + s.WR + s.TE;
    for (const k in s) s[k] = s[k] * 0.96 / tot;
    return s;
  }
  // Positional QUALITY — what number by position you own, NOT what round you
  // spent. 1st ≈ 1.00, 3rd ≈ 0.72, 6th ≈ 0.43, 12th ≈ 0.16 — summed per
  // position as a share of that position's starters.
  const POS_Q_DECAY = 6;
  function posQualityFill() {
    const src = SOURCES[st.rankSource] || SOURCES.jack;
    const byPos = {};
    for (const p of st.board) {
      const v = src.get(p);
      if (v == null) continue;
      (byPos[p.s] = byPos[p.s] || []).push([p, v]);
    }
    const idx = new Map();
    for (const k in byPos) {
      byPos[k].sort((a, b) => (src.desc ? b[1] - a[1] : a[1] - b[1]));
      byPos[k].forEach((e, i) => idx.set(e[0], i + 1));
    }
    const sl = st.slots;
    const starters = {
      QB: (sl.qb || 0) + (sl.sf || 0) || 1,
      RB: sl.rb || 1, WR: sl.wr || 1, TE: sl.te || 1,
    };
    const banked = { QB: 0, RB: 0, WR: 0, TE: 0 };
    for (const r of st.myRoster) {
      if (!r.p || banked[r.p.s] == null) continue;
      const n = idx.get(r.p);
      if (!n) continue;
      banked[r.p.s] += Math.exp(-(n - 1) / POS_Q_DECAY);
    }
    const out = {};
    for (const pos in banked) out[pos] = banked[pos] / Math.max(1, starters[pos]);
    return out;
  }
  function capitalDeficits() {
    const share = capitalShares();
    const banked = { QB: 0, RB: 0, WR: 0, TE: 0 };
    let spent = 0;
    for (const r of st.myRoster) {
      const v = pickValue(r.pickNo || Math.max(1, takenCount() / 2));
      spent += v;
      if (banked[r.pos] != null) banked[r.pos] += v;
    }
    const out = {};
    for (const pos in banked) {
      const target = share[pos] * spent;
      out[pos] = target > 0 ? (target - banked[pos]) / target : 0;
    }
    return out;
  }
  // Rank WITHIN position for every player, by the active rank source.
  function posRankIndex() {
    const src = SOURCES[st.rankSource] || SOURCES.jack;
    const posIdx = new Map();
    const byP = {};
    for (const p of st.board) {
      const v = src.get(p);
      if (v == null) continue;
      (byP[p.s] = byP[p.s] || []).push([p, v]);
    }
    for (const k in byP) {
      byP[k].sort((a, b) => (src.desc ? b[1] - a[1] : a[1] - b[1]));
      byP[k].forEach((e, i) => posIdx.set(e[0], i + 1));
    }
    return posIdx;
  }
  function draftedPosCounts() {
    const g = { QB: 0, RB: 0, WR: 0, TE: 0 };
    for (const p of st.board) if (g[p.s] != null && isDrafted(p)) g[p.s]++;
    return g;
  }
  // Format-aware need flags: capital-weighted counts, early RB2 window,
  // depletion schedule with quality-aware cycles, ahead-deletes-the-nag.
  function needPositions() {
    const c = rosterCounts();
    const ec = effRosterCounts();
    const rd = currentRound();
    const m = MODES[st.mode];
    const sl = st.slots;
    const need = new Set();
    if (m.qbFloor >= 2) {
      if (ec.QB < 1.9) need.add('QB');
    } else if (c.QB < 1 && rd >= 6) {
      need.add('QB');
    }
    // EARLY RB2 WINDOW (Jack, 2026-08-06, redraft only).
    if (st.mode.indexOf('re_') === 0 && rd >= 3 && rd <= 5 && c.RB < 2) need.add('RB');
    if (rd >= 5 && ec.RB < 2.6) need.add('RB');
    if (rd >= 5 && ec.WR < 3.4) need.add('WR');
    if (rd >= 7 && ec.TE < 0.75) need.add('TE');
    const lateRd = (sl.rounds || 16) - 2;
    if ((sl.k || 0) > 0 && rd >= lateRd && c.K < 1) need.add('K');
    if ((sl.dst || 0) > 0 && rd >= lateRd && c.DST < 1) need.add('DST');
    // DEPLETION SCHEDULE (Jack, 2026-08-06, redraft only).
    if (st.mode.indexOf('re_') === 0) {
      const gone = draftedPosCounts();
      const t = sl.teams || 12;
      const cap = {
        QB: (sl.qb || 0) + (sl.sf || 0) || 1,
        RB: (sl.rb || 1) + 1,
        WR: (sl.wr || 1) + 1,
        TE: sl.te || 1,
      };
      const posIdx = posRankIndex();
      for (const pos of ['QB', 'RB', 'WR', 'TE']) {
        const expect = Math.min(cap[pos], Math.floor(gone[pos] / t));
        if (!expect) continue;
        if (c[pos] < expect) { need.add(pos); continue; }
        if (pos !== 'RB' && pos !== 'WR') continue;
        // QUALITY-AWARE SCHEDULE: your k-th best has to belong to cycle k.
        const mine = st.myRoster
          .filter((r) => r.pos === pos && r.p && posIdx.get(r.p))
          .map((r) => posIdx.get(r.p)).sort((a, b) => a - b);
        const behind = mine.length < expect ||
          mine.slice(0, expect).some((rk, i) => rk > (i + 1) * t + t / 2);
        if (behind) need.add(pos);
        else if (expect >= 2) need.delete(pos);
      }
    }
    return need;
  }

  // ---------- pick recommendations (verbatim ESPN v0.17.9 engine) ----------
  function boardTiers(byPos) {
    const vk = modeKeys().vor;
    const tiers = new Map();
    for (const pos in byPos) {
      const peers = byPos[pos];
      let tier = 1;
      for (let i = 0; i < peers.length; i++) {
        if (i > 0) {
          const a = peers[i - 1][vk], b = peers[i][vk];
          if (a != null && b != null) {
            if (a - b >= 10) tier++;
          } else if (peers[i - 1].pPg != null && peers[i].pPg != null &&
                     peers[i - 1].pPg - peers[i].pPg >= 2.5) {
            tier++;
          }
        }
        tiers.set(peers[i], tier);
      }
    }
    return tiers;
  }

  function recommendPicks() {
    const avail = availablePlayers();
    const sortedAll = sortListBySource(avail);
    let board = sortedAll.slice(0, 30);
    if (!board.length) return [];
    const sl = st.slots;
    const c = rosterCounts();
    const ec = effRosterCounts();
    const deficits = capitalDeficits();
    const rd = currentRound();
    const dampen = Math.min(1, rd / 8);
    const fadeRamp = rd <= 4 ? 0 : Math.min(1, (rd - 4) / 4);
    const lateRd = (sl.rounds || 16) - 2;
    const lateWindow = rd >= Math.ceil((sl.rounds || 16) * 0.66);
    const lateFaller = (q) => lateWindow && adpTag(q) === 'STEAL';
    const qfill = posQualityFill();
    // ADP RELIABILITY DECAY: full trust through round 6, zero by round 12.
    const adpTrust = Math.max(0, Math.min(1, (12 - rd) / 6));
    // ROSTER LOCK: remaining picks only just cover mandatory K/DST slots.
    const spotsLeft = Math.max(0, (sl.rounds || 16) - (st.myRoster || []).length);
    const mustFill = [];
    if ((sl.k || 0) > 0 && (c.K || 0) < (sl.k || 0)) mustFill.push('K');
    if ((sl.dst || 0) > 0 && (c.DST || 0) < (sl.dst || 0)) mustFill.push('DST');
    const rosterLocked = mustFill.length > 0 && spotsLeft <= mustFill.length;
    if (rosterLocked) {
      // Top slice of EACH forced position, not of the merged pool.
      let fill = [];
      for (const pos of mustFill) {
        fill = fill.concat(sortListBySource(avail.filter((q) => q.s === pos)).slice(0, 15));
      }
      if (fill.length) board = sortListBySource(fill).slice(0, 30);
    }
    const remStarters = {
      QB: Math.max(0, (sl.qb || 0) + (sl.sf || 0) - c.QB),
      RB: Math.max(0, (sl.rb || 0) - c.RB),
      WR: Math.max(0, (sl.wr || 0) - c.WR),
      TE: Math.max(0, (sl.te || 0) - c.TE),
    };
    const openSlots = ['QB', 'RB', 'WR', 'TE'].filter((k) => remStarters[k] > 0);
    const byPos = {};
    for (const p of board) (byPos[p.s] = byPos[p.s] || []).push(p);
    // Cliff detection needs the FULL pool.
    const byPosAll = {};
    for (const p of sortedAll) (byPosAll[p.s] = byPosAll[p.s] || []).push(p);
    const vk = modeKeys().vor;
    const tiers = boardTiers(byPos);
    const sfMode = st.mode.endsWith('_sf');
    const supply = {};
    for (const q of avail) {
      if ((q[vk] || 0) > 0) supply[q.s] = (supply[q.s] || 0) + 1;
    }
    const need = needPositions();
    const _needPosIdx = posRankIndex();
    const _needGone = draftedPosCounts();
    const _needT = sl.teams || 12;
    const scored = board.map((p, idx) => {
      let score = Math.max(0, 30 - idx);
      const reasons = [];
      let rosterPen = 0;
      if (idx === 0) reasons.push('Best on board');
      if (p[vk] != null) score += p[vk] / 10;
      const tier = tiers.get(p);
      if (tier === 1) { score += 6; reasons.push('Tier 1 ' + p.s); }
      else if (tier === 2) score += 3;
      const defc = deficits[p.s] != null ? deficits[p.s] : 0;
      const qf = qfill[p.s] != null ? qfill[p.s] : 0;
      if (defc > 0.15 && st.myRoster.length >= 2) {
        let b = Math.min(8, 10 * defc) * dampen * Math.max(0, 1 - qf);
        b = Math.round(b * 10) / 10;
        score += b;
        if (b >= 3) reasons.push('Needs ' + p.s + ' value');
      } else if (defc < -0.35 && fadeRamp > 0) {
        let fade = Math.min(20, -7 * defc) * fadeRamp;
        if (lateFaller(p)) fade *= 0.25;
        score -= fade;
        rosterPen += fade;
        if (fade >= 5) reasons.push(p.s + ' capital full');
      }
      if (qf > 0.5) {
        let qFade = Math.min(30, 45 * (qf - 0.5)) * dampen;
        if (lateFaller(p)) qFade *= 0.25;
        score -= qFade;
        rosterPen += qFade;
        if (qFade >= 5) reasons.push(p.s + ' set — ' + Math.round(qf * 100) + '% quality');
      }
      // EARLY RB2 PUSH (redraft only).
      if (st.mode.indexOf('re_') === 0 && p.s === 'RB' && rd >= 3 && rd <= 5 && c.RB < 2) {
        score += (2 - c.RB) * 5;
        reasons.push(c.RB === 0 ? 'No RB yet — rounds 3-5 window' : 'RB2 window (rounds 3-5)');
      }
      // NEED BOOST, gated on schedule-repairing candidates only.
      if (need.has(p.s)) {
        const pr = _needPosIdx.get(p);
        const bound = (Math.floor((_needGone[p.s] || 0) / _needT) + 1) * _needT + _needT / 2;
        if (pr == null || pr <= bound) { score += 4; reasons.push('NEED ' + p.s); }
      }
      if (remStarters[p.s] > 0) {
        const lastSlot = openSlots.length === 1;
        score += lastSlot ? 7 : 4;
        reasons.push(lastSlot ? 'LAST open slot: ' + p.s : 'Open ' + p.s + ' slot');
      }
      else if (sfMode && p.s === 'QB' && ec.QB < 3.2 && defc > -0.5) { score += 4; reasons.push('SF QB depth'); }
      const sup = supply[p.s] || 0;
      if (sup > 0 && sup <= 3) { score += 5; reasons.push('Only ' + sup + ' startable ' + p.s + (sup === 1 ? '' : 's') + ' left'); }
      else if (sup > 0 && sup <= 6) score += 2.5;
      if (p.scDelta) {
        score += Math.max(-6, Math.min(6, p.scDelta * 1.5));
        if (p.scDelta >= 1) reasons.push('Scoring +' + p.scDelta.toFixed(1) + ' ppg');
        else if (p.scDelta <= -1) reasons.push('Scoring −' + Math.abs(p.scDelta).toFixed(1) + ' ppg');
      }
      // ADP votes on exactly ONE question: will he last to your NEXT pick?
      const nextPk = myNextPickOverall();
      const padp = p[modeKeys().adp];
      if (nextPk != null && padp != null && padp >= nextPk) {
        const fadeMult = (sfMode && p.s === 'QB') ? 0.5 : 1;
        const over = padp - nextPk;
        const fade = Math.min(16, 6 + over * 0.7) * fadeMult * adpTrust;
        score -= fade;
        if (fade >= 3) reasons.push('Likely there at your next pick');
      }
      const stk = stackInfo(p);
      if (stk && stk.type === 'stack') {
        if (st.mode.indexOf('re_') === 0) score += 1;
        else { score += 3; reasons.push('Stacks w/ ' + stk.names[0]); }
      }
      // Cliff: whole-pool successor gap, scaled with the gap.
      const peersAll = byPosAll[p.s] || [];
      const nxt = peersAll[peersAll.indexOf(p) + 1];
      if (nxt) {
        const a = p[vk], b = nxt[vk];
        if (a != null && b != null && a - b >= 12) {
          const bonus = Math.min(10, 4 + (a - b) * 0.15);
          score += bonus;
          reasons.push('Cliff: next ' + p.s + ' −' + Math.round(a - b) + ' VOR');
        } else if (p.pPg != null && nxt.pPg != null && p.pPg - nxt.pPg >= 2.5) {
          const bonus = Math.min(10, 4 + (p.pPg - nxt.pPg) * 0.9);
          score += bonus;
          reasons.push('Cliff: next ' + p.s + ' −' + (Math.round((p.pPg - nxt.pPg) * 10) / 10) + ' ppg');
        }
      } else if (peersAll.length === 1) {
        score += 10; reasons.push('Last startable ' + p.s);
      }
      if (rosterLocked) {
        if (mustFill.indexOf(p.s) < 0) {
          score -= 100;
          rosterPen += 100;
          reasons.push('No spots left — must draft ' + mustFill.join(' + '));
        } else {
          score += 25;
          reasons.push('Required: ' + spotsLeft + ' pick' + (spotsLeft === 1 ? '' : 's') + ' for ' + mustFill.join(' + '));
        }
      } else if ((p.s === 'K' || p.s === 'DST') && rd < lateRd) { score -= 25; rosterPen += 25; }
      // Backup QB/TE: elite closes the position, abundance kills, surplus scales.
      if (st.mode.indexOf('re_') === 0) {
        const qbStarters = (sl.qb || 0) + (sl.sf || 0) || 1;
        const teStarters = sl.te || 1;
        const backupPenalty = rd <= 9 ? 40 : rd < lateRd ? 15 : 5;
        const lastTwo = rd >= (sl.rounds || 16) - 1;
        const closed = (pos) => {
          const q = qfill[pos] != null ? qfill[pos] : 0;
          return q >= 0.5 && !(lastTwo && adpTag(p) === 'STEAL');
        };
        const penaltyFor = (pos, have, starters) =>
          (closed(pos) || have > starters ? 60 : backupPenalty);
        const surplus = (pos, have, starters) =>
          p.s === pos && have >= starters ? (have - starters + 1) : 0;
        const qbX = surplus('QB', c.QB, qbStarters);
        const teX = surplus('TE', c.TE, teStarters);
        if (qbX) {
          const pen = penaltyFor('QB', c.QB, qbStarters) * qbX;
          score -= pen;
          rosterPen += pen;
          if (closed('QB')) reasons.push('Elite QB rostered — waivers are the backup');
          else if (qbX >= 2) reasons.push('Already have ' + c.QB + ' QBs');
        }
        if (teX) {
          const pen = penaltyFor('TE', c.TE, teStarters) * teX;
          score -= pen;
          rosterPen += pen;
          if (closed('TE')) reasons.push('Elite TE rostered — waivers are the backup');
          else if (teX >= 2) reasons.push('Already have ' + c.TE + ' TEs');
        }
      }
      return { p, score: Math.round(score * 10) / 10, reasons, rosterPen };
    });
    // ---- leapfrog guard (with roster-penalty exemption) ----
    const nextMine = myNextPickOverall();
    const idxOf = new Map();
    board.forEach((p, i) => idxOf.set(p, i));
    const leapfrogOk = (later, better) => {
      if ((better.rosterPen || 0) >= 10) return true;
      const adp = better.p[modeKeys().adp];
      const survives = adpTrust > 0.35 && nextMine != null && adp != null && adp > nextMine + 2;
      const close = (idxOf.get(later.p) - idxOf.get(better.p)) <= 5;
      if (survives && close) {
        if (!later._lfReason && later.p.s === better.p.s) {
          later.reasons.push(better.p.n.split(' ').pop() + ' should last to your next pick');
          later._lfReason = true;
        }
        return true;
      }
      if (later.p.s === better.p.s) return false;
      return need.has(later.p.s) && (supply[better.p.s] || 0) >= 8;
    };
    const boardOrder = scored.slice().sort((a, b) => idxOf.get(a.p) - idxOf.get(b.p));
    for (let i = 0; i < boardOrder.length; i++) {
      for (let j = 0; j < i; j++) {
        const better = boardOrder[j], later = boardOrder[i];
        if (later.score > better.score && !leapfrogOk(later, better)) {
          later.score = Math.round((better.score - 0.5) * 10) / 10;
        }
      }
    }
    scored.sort((a, b) => b.score - a.score);
    // Locked with BOTH K and D/ST open: cover one of each in the top recs.
    if (rosterLocked && mustFill.length > 1) {
      const first = [];
      for (const pos of mustFill) {
        const best = scored.find((s) => s.p.s === pos && first.indexOf(s) < 0);
        if (best) first.push(best);
      }
      const rest = scored.filter((s) => first.indexOf(s) < 0);
      return first.concat(rest).slice(0, 3);
    }
    return scored.slice(0, 3);
  }

  // Harness/console-compatible wrapper (v0.4.x shape).
  function displayRec(p) {
    const rec = poolByBoard.get(p);
    if (rec) return rec;
    return { pid: 0, name: p.n, pos: p.s, team: p.sTm || '', bye: p.bye || 0,
      inj: '', yAdp: p[modeKeys().adp] || 999, orank: 9999, proj: p.szn || 0, b: p };
  }
  function recommend() {
    const recs = recommendPicks();
    const top = recs.map((x) => ({
      r: displayRec(x.p), p: x.p,
      sc: x.score, score: x.score,
      chips: x.reasons, reasons: x.reasons,
      rosterPen: x.rosterPen,
    }));
    return { top, all: top, nextPick: nextPickNo(), rnd: currentRound() };
  }

  // ---------- UI ----------
  let root = null;
  function el(html) { const d = document.createElement('div'); d.innerHTML = html; return d.firstElementChild; }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }

  const CSS = {
    panel: 'position:fixed;top:64px;right:10px;width:340px;max-height:84vh;z-index:2147483000;background:#0e0916;border:1px solid #7d2eff;border-radius:10px;color:#e5e7eb;font:12px/1.45 system-ui,sans-serif;box-shadow:0 8px 30px rgba(0,0,0,.55);display:flex;flex-direction:column;overflow:hidden',
    head: 'padding:8px 12px;background:#1d1430;border-bottom:1px solid #3b2b55;display:flex;align-items:center;gap:8px;cursor:move',
    tabs: 'display:flex;gap:2px;padding:6px 8px 0;border-bottom:1px solid #33245c',
    tab: (on) => 'flex:1;text-align:center;padding:6px 4px;border-radius:6px 6px 0 0;cursor:pointer;font-weight:700;letter-spacing:.4px;font-size:11px;' + (on ? 'background:#7d2eff;color:#fff' : 'background:#1c142e;color:#a89cc8'),
    body: 'overflow-y:auto;padding:8px;flex:1',
    card: 'background:#171025;border:1px solid #33245c;border-radius:8px;padding:8px 10px;margin-bottom:7px;position:relative',
    chip: 'display:inline-block;background:#2a2140;color:#c9a4ff;border-radius:4px;padding:1px 6px;margin:2px 3px 0 0;font-size:10px',
    row: 'display:flex;align-items:center;gap:8px;padding:5px 6px;border-bottom:1px solid #251a3e',
    posBtn: (on) => 'padding:3px 8px;border-radius:5px;cursor:pointer;font-size:10px;font-weight:700;' + (on ? 'background:#7d2eff;color:#fff' : 'background:#1c142e;color:#a89cc8'),
    select: 'background:#1c142e;color:#cfc7e8;border:1px solid #33245c;border-radius:5px;font-size:10px;padding:2px 4px',
  };
  const POS_COLORS = { QB: '#ef4444', RB: '#22c55e', WR: '#3b82f6', TE: '#f59e0b', K: '#a78bfa', DST: '#94a3b8', DEF: '#94a3b8' };
  const MEDALS = ['#ff4040', '#c0c7d1', '#c9926b'];
  const TAG_COLORS = {
    STEAL: 'background:#0d3321;color:#4ade80', Value: 'background:#0d2b33;color:#38bdf8',
    Reach: 'background:#33130d;color:#f87171', Stretch: 'background:#332a0d;color:#fbbf24',
  };

  // One panel, ESPN-helper style: header DRAFT | SEASON toggle.
  let uiMode = 'draft';
  function syncPanels() {
    ['mff-sidebar', 'mff-reopen'].forEach((id) => {
      const n = document.getElementById(id);
      if (!n) return;
      const want = uiMode === 'draft' ? 'none' : '';
      if (n.style.display !== want) n.style.display = want;
    });
    if (root) root.style.display = uiMode === 'draft' ? 'flex' : 'none';
    ensureDraftChip();
  }
  window.__mffYahooSetMode = function (m) { uiMode = m === 'season' ? 'season' : 'draft'; syncPanels(); if (uiMode === 'draft') render(); };
  // Way back from SEASON: the season sidebar + its reopen chip render at
  // z-index 2147483647 (max) and the reopen chip sits bottom-right 18px —
  // exactly where this chip used to live, one z-layer above it, so it was
  // unclickable and season mode was a one-way door (v0.5.0 bug). Now it sits
  // ABOVE the sidebar's box (sidebar starts at top:70px), carries the same
  // max z-index, and re-appends to <body> every sync tick so later-mounted
  // equal-z elements can never paint over it.
  function ensureDraftChip() {
    let chip = document.getElementById('mffYdBackChip');
    if (uiMode !== 'season') { if (chip) chip.remove(); return; }
    if (!chip) {
      chip = el('<div id="mffYdBackChip" style="position:fixed;top:30px;right:12px;z-index:2147483647;background:#7d2eff;color:#fff;border-radius:7px;padding:8px 15px;font:700 12px system-ui;cursor:pointer;letter-spacing:.8px;box-shadow:0 4px 14px rgba(0,0,0,.6);border:1px solid #c9a4ff">⟵ BACK TO DRAFT</div>');
      chip.addEventListener('click', () => window.__mffYahooSetMode('draft'));
    }
    document.body.appendChild(chip); // (re-)append: last in DOM wins ties
  }

  function ensureScrollbarCss() {
    if (document.getElementById('mffYdScrollCss')) return;
    const sty = document.createElement('style');
    sty.id = 'mffYdScrollCss';
    sty.textContent =
      '#mffYahooDraft *{scrollbar-width:thin;scrollbar-color:#5b21b6 #140e20}' +
      '#mffYahooDraft *::-webkit-scrollbar{width:8px;height:8px}' +
      '#mffYahooDraft *::-webkit-scrollbar-track{background:#140e20}' +
      '#mffYahooDraft *::-webkit-scrollbar-thumb{background:#5b21b6;border-radius:4px}' +
      '#mffYahooDraft *::-webkit-scrollbar-thumb:hover{background:#7d2eff}';
    document.head.appendChild(sty);
  }
  function mount() {
    if (root) return;
    root = el('<div id="mffYahooDraft" style="' + CSS.panel + '"></div>');
    ensureScrollbarCss();
    document.body.appendChild(root);
    enableDragResize();
    syncPanels();
    setInterval(syncPanels, 2000);
    render();
  }

  // Drag (header) + resize (corner handle). Delegated on root and bound ONCE
  // in mount() — render() wipes root.innerHTML on every update, so listeners
  // on the header/handle elements themselves would die at the first re-render.
  // Position/size land on the root element's inline style, which render()
  // never touches, so they survive updates.
  function enableDragResize() {
    let drag = null, rez = null;
    root.addEventListener('mousedown', (e) => {
      if (e.target.closest('#mffYdResize')) {
        const r = root.getBoundingClientRect();
        rez = { sx: e.clientX, sy: e.clientY, w: r.width, h: r.height };
        e.preventDefault();
        return;
      }
      const head = e.target.closest('#mffYdHead');
      if (head && !e.target.closest('[data-mode]')) {
        const r = root.getBoundingClientRect();
        drag = { sx: e.clientX, sy: e.clientY, x: r.left, y: r.top };
        e.preventDefault();
      }
    });
    window.addEventListener('mousemove', (e) => {
      if (drag) {
        root.style.left = Math.max(0, Math.min(window.innerWidth - 60, drag.x + e.clientX - drag.sx)) + 'px';
        root.style.top = Math.max(0, Math.min(window.innerHeight - 40, drag.y + e.clientY - drag.sy)) + 'px';
        root.style.right = 'auto';
      } else if (rez) {
        root.style.maxHeight = 'none';
        root.style.width = Math.max(300, rez.w + (e.clientX - rez.sx)) + 'px';
        root.style.height = Math.max(220, rez.h + (e.clientY - rez.sy)) + 'px';
      }
    });
    window.addEventListener('mouseup', () => { drag = null; rez = null; });
  }

  function fmtClock(sec) {
    if (sec == null) return '';
    const m = Math.floor(sec / 60), s = sec % 60;
    return m + ':' + String(s).padStart(2, '0');
  }

  let renderTimer = null;
  function scheduleRender() {
    if (renderTimer) return;
    renderTimer = setTimeout(() => { renderTimer = null; render(); }, 250);
  }
  function renderClock() {
    const c = root && root.querySelector('#mffYdClock');
    if (c && st.clock != null) c.textContent = fmtClock(st.clock);
  }

  function teamLabel(tid) { return st.teams[tid] || ('Team ' + tid); }

  function tickerHTML() {
    const nos = Object.keys(st.picks).map(Number).sort((a, b) => a - b).slice(-3).reverse();
    if (!nos.length) return '';
    const t = st.slots.teams || 12;
    return '<div style="font-size:9px;color:#8d81ad;display:flex;flex-direction:column;gap:1px;padding:2px 4px 6px">' +
      nos.map((no) => {
        const pk = st.picks[no];
        const rec = st.pool[pk.pid];
        const rd = Math.ceil(no / t), rp = ((no - 1) % t) + 1;
        return '<div>' + rd + '.' + String(rp).padStart(2, '0') + ' <b style="color:#c6bde0">' +
          esc(rec ? rec.name : '#' + pk.pid) + '</b> ' + esc(rec ? rec.pos : '') +
          ' <span style="color:#665c85">— ' + esc(teamLabel(pk.tid)) + '</span></div>';
      }).join('') + '</div>';
  }

  function remainingStartersHTML() {
    const sl = st.slots;
    const c = rosterCounts();
    const req = { QB: (sl.qb || 0) + (sl.sf || 0), RB: sl.rb || 0, WR: sl.wr || 0, TE: sl.te || 0 };
    if (!req.QB && !req.RB && !req.WR && !req.TE) return '';
    return '<div style="display:flex;gap:4px;margin:0 0 7px">' +
      ['QB', 'RB', 'WR', 'TE'].map((pos) =>
        '<div style="flex:1;text-align:center;background:#171025;border:1px solid #33245c;border-radius:6px;padding:3px 0">' +
        '<div style="font-size:13px;font-weight:800;color:' + POS_COLORS[pos] + '">' + Math.max(0, req[pos] - c[pos]) + '</div>' +
        '<div style="font-size:9px;color:#8d81ad;letter-spacing:.5px">' + pos + '</div></div>'
      ).join('') + '</div>';
  }

  function recCardsHTML() {
    const recs = recommendPicks();
    if (!recs.length) return '<div style="color:#a89cc8;padding:10px">Waiting for draft feed…</div>';
    return recs.map((x, i) => {
      const p = x.p;
      const rec = poolByBoard.get(p);
      const tag = adpTag(p);
      const padp = p[modeKeys().adp];
      const chips =
        (tag ? '<span style="' + CSS.chip + ';' + (TAG_COLORS[tag] || '') + '">' + tag + '</span>' : '') +
        x.reasons.map((r) => '<span style="' + CSS.chip + '">' + esc(r) + '</span>').join('') +
        (rec && rec.inj ? '<span style="' + CSS.chip + ';background:#33130d;color:#f87171">' + esc(rec.inj) + '</span>' : '');
      return '<div style="' + CSS.card + (i === 0 ? ';border-color:#7d2eff' : '') + '">' +
        '<div style="display:flex;align-items:baseline;gap:8px">' +
        '<b style="font-size:15px;color:' + MEDALS[i] + '">' + (i + 1) + '</b>' +
        '<b style="font-size:13px">' + esc(p.n) + '</b>' +
        '<span style="color:' + (POS_COLORS[p.s] || '#a89cc8') + ';font-weight:700">' + p.s + '</span>' +
        '<span style="color:#a89cc8">' + esc(p.sTm || '') + (rec && rec.bye ? ' · Bye ' + rec.bye : '') + '</span>' +
        '<span style="margin-left:auto;color:' + MEDALS[i] + ';font-weight:700">' + x.score + '</span></div>' +
        '<div style="color:#a89cc8;font-size:10px;margin-top:2px">' +
        'Jack #' + (p[modeKeys().jack] != null ? p[modeKeys().jack] : p.rank) +
        (p.pPg != null ? ' · ' + p.pPg + ' ppg' : '') +
        (padp != null ? ' · ADP ' + padp : '') +
        (rec && rec.yAdp < 900 ? ' · Y! ' + rec.yAdp.toFixed(1) : '') + '</div>' +
        (chips ? '<div>' + chips + '</div>' : '') + '</div>';
    }).join('');
  }

  function searchHTML() {
    let sugg = '';
    if (st.searchQ.length >= 2) {
      const q = norm(st.searchQ);
      const hits = st.board.filter((p) => norm(p.n).indexOf(q) >= 0).slice(0, 8);
      sugg = hits.map((p) => {
        const k = keyOf(p);
        const drafted = isDrafted(p);
        const manual = st.manualDrafted.has(k) || st.manualMine.has(k);
        return '<div style="' + CSS.row + '">' +
          '<span style="flex:1;' + (drafted ? 'color:#7a6f99;text-decoration:line-through' : '') + '">' +
          esc(p.n) + ' <span style="color:' + (POS_COLORS[p.s] || '#a89cc8') + '">' + p.s + '</span></span>' +
          (manual
            ? '<span data-undo="' + esc(k) + '" style="cursor:pointer;color:#fbbf24;font-weight:700">↺</span>'
            : drafted ? '<span style="color:#544a70">taken</span>'
            : '<span data-gone="' + esc(k) + '" style="cursor:pointer;color:#f87171;font-weight:700;padding:0 6px">✕</span>' +
              '<span data-mine="' + esc(k) + '" style="cursor:pointer;color:#4ade80;font-weight:700">＋</span>') +
          '</div>';
      }).join('');
    }
    return '<div style="margin-top:4px"><input id="mffYdSearch" type="text" placeholder="Search… (✕ drafted / ＋ my pick)" value="' + esc(st.searchQ) + '" autocomplete="off" ' +
      'style="width:100%;box-sizing:border-box;background:#1c142e;border:1px solid #33245c;border-radius:6px;color:#e5e7eb;font-size:11px;padding:5px 8px">' +
      '<div>' + sugg + '</div></div>';
  }

  function stacksHTML() {
    const qbs = st.myRoster.filter((r) => r.pos === 'QB' && r.p && r.p.sTm);
    if (!qbs.length) return '';
    const inner = qbs.map((qb) => {
      const tm = qb.p.sTm;
      const have = st.myRoster.filter((r) => r !== qb && r.p && r.p.sTm === tm);
      const targets = sortListBySource(
        availablePlayers().filter((p) => p.sTm === tm && (p.s === 'WR' || p.s === 'TE'))
      ).slice(0, 3);
      return '<div style="margin-bottom:6px">' +
        '<div style="color:#6dd0a8;font-weight:700;font-size:11px">' + esc(qb.name) + ' <span style="color:#7a6f99">(' + esc(tm) + ')</span></div>' +
        have.map((r) => '<div style="' + CSS.row + '"><span style="color:#7a6f99">' + esc(r.pos) + '</span><span style="flex:1;color:#6dd0a8">' + esc(r.name) + ' ✓</span></div>').join('') +
        (targets.map((t) => '<div style="' + CSS.row + '"><span style="color:#7a6f99">' + esc(t.s) + '</span><span style="flex:1">' + esc(t.n) + '</span>' +
          '<span style="color:#a89cc8">' + (t.pPg != null ? t.pPg + 'ppg' : '—') + '</span></div>').join('') ||
          '<div style="color:#544a70;padding:2px 6px">No pass-catchers left on ' + esc(tm) + '</div>') +
        '</div>';
    }).join('');
    return '<div style="margin-top:8px"><div style="color:#8d81ad;font-size:10px;font-weight:700;letter-spacing:.6px;margin-bottom:3px">STACKS</div>' + inner + '</div>';
  }

  function render() {
    if (!root || !st.ready) return;
    const until = picksUntilMine();
    const onClock = teamLabel(st.onClockTeam);
    const nextNo = nextPickNo();
    const t = st.slots.teams || 12;
    const rd = Math.ceil(nextNo / t), rdPick = ((nextNo - 1) % t) + 1;
    let h = '<div id="mffYdHead" style="' + CSS.head + '" title="Drag to move"><b style="color:#c9a4ff;letter-spacing:.6px">MFF YAHOO HELPER</b>' +
      '<span style="display:flex;border:1px solid #3b2b55;border-radius:5px;overflow:hidden;font-size:9px;font-weight:700;letter-spacing:.8px">' +
      '<span data-mode="draft" style="padding:2px 7px;cursor:pointer;background:#7d2eff;color:#fff">DRAFT</span>' +
      '<span data-mode="season" style="padding:2px 7px;cursor:pointer;background:#1c142e;color:#a89cc8">SEASON</span></span>' +
      '<span style="color:#a89cc8;font-size:10px;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' +
      esc(st.leagueName) + ' · ' + t + 'tm · ' + esc(st.scoringLabel) + '</span>' +
      '<span id="mffYdClock" style="color:#fbbf24;font-weight:700">' + fmtClock(st.clock) + '</span></div>';
    const started = st.currentPick > 0 && st.onClockTeam > 0;
    const done = st.order.length && nextNo > st.order.length;
    h += '<div style="padding:5px 12px;background:#140e20;border-bottom:1px solid #251a3e;font-size:11px;color:#cfc7e8">' +
      (done ? '<b>DRAFT COMPLETE</b>' : started
        ? 'Pick ' + rd + '.' + String(rdPick).padStart(2, '0') + ' · #' + nextNo + ' · <b>' + esc(onClock) + '</b>'
        : 'Waiting for the draft to start') +
      (!done && until != null ? ' · <span style="color:' + (until <= 1 ? '#f87171' : '#4ade80') + ';font-weight:700">' +
        (until <= 0 ? 'ON THE CLOCK' : 'you in ' + until) + '</span>' : '') + '</div>';
    h += '<div style="' + CSS.tabs + '">' +
      '<div data-t="recs" style="' + CSS.tab(st.tab === 'recs') + '">RECS</div>' +
      '<div data-t="board" style="' + CSS.tab(st.tab === 'board') + '">BOARD</div>' +
      '<div data-t="roster" style="' + CSS.tab(st.tab === 'roster') + '">ROSTER (' + st.myRoster.length + ')</div></div>';
    h += '<div style="' + CSS.body + '" id="mffYdBody"></div>';
    h += '<div id="mffYdResize" title="Drag to resize" style="position:absolute;right:0;bottom:0;width:20px;height:20px;cursor:nwse-resize;z-index:5;background:linear-gradient(135deg,transparent 50%,#7d2eff 50%);opacity:.65;border-radius:0 0 9px 0"></div>';
    root.innerHTML = h;
    root.querySelectorAll('[data-t]').forEach((tb) =>
      tb.addEventListener('click', () => { st.tab = tb.getAttribute('data-t'); render(); }));
    root.querySelectorAll('[data-mode]').forEach((tb) =>
      tb.addEventListener('click', () => window.__mffYahooSetMode(tb.getAttribute('data-mode'))));
    const body = root.querySelector('#mffYdBody');

    if (st.tab === 'recs') {
      let modeOpts = '';
      for (const k in MODES) modeOpts += '<option value="' + k + '"' + (st.mode === k ? ' selected' : '') + '>' + MODES[k].label + '</option>';
      let srcOpts = '';
      for (const k in SOURCES) srcOpts += '<option value="' + k + '"' + (st.rankSource === k ? ' selected' : '') + '>' + SOURCES[k].label + '</option>';
      body.innerHTML = tickerHTML() + remainingStartersHTML() +
        '<div style="display:flex;gap:4px;margin-bottom:6px">' +
        '<select id="mffYdMode" style="' + CSS.select + ';flex:1">' + modeOpts + '</select>' +
        '<select id="mffYdSrc" style="' + CSS.select + ';flex:1">' + srcOpts + '</select></div>' +
        '<div style="color:#8d81ad;font-size:10px;font-weight:700;letter-spacing:.6px;margin-bottom:3px">RECOMMENDED</div>' +
        recCardsHTML() + searchHTML() + stacksHTML();
      const modeSel = body.querySelector('#mffYdMode');
      if (modeSel) modeSel.addEventListener('change', () => { st.mode = modeSel.value; render(); });
      const srcSel = body.querySelector('#mffYdSrc');
      if (srcSel) srcSel.addEventListener('change', () => { st.rankSource = srcSel.value; render(); });
      wireSearch(body);
    } else if (st.tab === 'board') {
      let bar = '<div style="margin-bottom:6px;display:flex;gap:4px;flex-wrap:wrap">';
      ['ALL', 'QB', 'RB', 'WR', 'TE', 'K', 'DST'].forEach((p) => {
        bar += '<span data-p="' + p + '" style="' + CSS.posBtn(st.posFilter === p) + '">' + (p === 'DST' ? 'DEF' : p) + '</span>';
      });
      bar += '<span id="mffYdVor" title="Sort by VOR (format-aware)" style="' + CSS.posBtn(st.sortVor) + '">VOR</span></div>';
      const vk = modeKeys().vor;
      const avail = sortedAvailable();
      body.innerHTML = bar + avail.slice(0, 60).map((p) => {
        const rec = poolByBoard.get(p);
        const tag = adpTag(p);
        const rk = SOURCES[st.rankSource].get(p);
        return '<div style="' + CSS.row + '">' +
          '<span style="color:#7a6f99;min-width:28px">' + (rk != null ? '#' + rk : '') + '</span>' +
          '<span style="flex:1"><b>' + esc(p.n) + '</b> <span style="color:' + (POS_COLORS[p.s] || '#a89cc8') + '">' + p.s + '</span>' +
          ' <span style="color:#7a6f99">' + esc(p.sTm || '') + '</span>' +
          (tag ? ' <span style="font-size:9px;border-radius:3px;padding:0 4px;' + (TAG_COLORS[tag] || '') + '">' + tag + '</span>' : '') + '</span>' +
          '<span style="color:#a89cc8;min-width:28px;text-align:right" title="ADP">' + (p[modeKeys().adp] != null ? p[modeKeys().adp] : '—') + '</span>' +
          '<span style="color:#4ade80;min-width:30px;text-align:right" title="VOR">' + (p[vk] != null ? Math.round(p[vk]) : '—') + '</span>' +
          '<span style="color:#38bdf8;min-width:32px;text-align:right" title="proj ppg">' + (p.pPg != null ? p.pPg : (rec ? rec.proj.toFixed(0) : '—')) + '</span></div>';
      }).join('');
      body.querySelectorAll('[data-p]').forEach((s) =>
        s.addEventListener('click', () => { st.posFilter = s.getAttribute('data-p'); render(); }));
      const vb = body.querySelector('#mffYdVor');
      if (vb) vb.addEventListener('click', () => { st.sortVor = !st.sortVor; render(); });
    } else {
      const bySlot = {};
      st.myRoster.forEach((r) => { (bySlot[r.pos] = bySlot[r.pos] || []).push(r); });
      const sl = st.slots;
      const starters = { QB: (sl.qb || 0) + (sl.sf || 0), RB: sl.rb, WR: sl.wr, TE: sl.te, K: sl.k, DST: sl.dst };
      body.innerHTML =
        '<div style="margin-bottom:7px;background:#171025;border:1px solid #33245c;border-radius:6px;padding:5px 10px;color:#cfc7e8">' +
        'Starter proj: <b style="color:#4ade80">' + starterProjPPG() + ' ppg</b></div>' +
        ['QB', 'RB', 'WR', 'TE', 'K', 'DST'].map((pos) => {
          const list = bySlot[pos] || [];
          return '<div style="margin-bottom:6px"><div style="color:' + (POS_COLORS[pos] || '#a89cc8') +
            ';font-weight:700;font-size:10px;letter-spacing:.6px">' + (pos === 'DST' ? 'DEF' : pos) + ' (' + list.length + '/' + (starters[pos] || 0) + ' starters)</div>' +
            (list.map((r) => {
              const rec = r.p ? poolByBoard.get(r.p) : null;
              return '<div style="' + CSS.row + '"><span style="color:#7a6f99;min-width:30px">' +
                (r.pickNo ? Math.ceil(r.pickNo / (sl.teams || 12)) + '.' + String(((r.pickNo - 1) % (sl.teams || 12)) + 1).padStart(2, '0') : 'man') + '</span>' +
                '<span style="flex:1">' + esc(r.name) + '</span>' +
                '<span style="color:#7a6f99">' + (r.p && r.p.pPg != null ? r.p.pPg + 'ppg' : '') +
                (rec && rec.bye ? ' · B' + rec.bye : '') + '</span></div>';
            }).join('') || '<div style="color:#544a70;padding:2px 6px">—</div>') + '</div>';
        }).join('') + stacksHTML();
    }
  }

  function wireSearch(body) {
    const inp = body.querySelector('#mffYdSearch');
    if (inp) {
      inp.addEventListener('input', () => { st.searchQ = inp.value; render();
        const again = root.querySelector('#mffYdSearch');
        if (again) { again.focus(); again.setSelectionRange(again.value.length, again.value.length); } });
    }
    body.querySelectorAll('[data-gone]').forEach((s) => s.addEventListener('click', () => {
      st.manualDrafted.add(s.getAttribute('data-gone')); rebuildFromPicks(); render();
    }));
    body.querySelectorAll('[data-mine]').forEach((s) => s.addEventListener('click', () => {
      st.manualMine.add(s.getAttribute('data-mine')); rebuildFromPicks(); render();
    }));
    body.querySelectorAll('[data-undo]').forEach((s) => s.addEventListener('click', () => {
      const k = s.getAttribute('data-undo');
      st.manualDrafted.delete(k); st.manualMine.delete(k); rebuildFromPicks(); render();
    }));
  }

  // ---------- boot ----------
  Promise.all([
    getJson(API + 'settings/nfl/' + st.leagueId + '?format=rawjson').then((j) => applySettings(j.service || j)),
    getJson(API + 'teams/nfl/' + st.leagueId + '?format=rawjson').then((j) => applyTeams(j.service || j)),
    getJson(API + 'players/nfl/' + st.leagueId + '?images=1&team_id=' + st.myTeamId + '&projected=1&average=1&format=rawjson')
      .then((j) => applyPlayers(j.service || j)),
    loadBoard().then((pj) => { st.board = (pj && pj.players) || []; indexBoard(); }),
  ]).then(backfill).then(() => {
    linkBoard();
    applyLeagueScoring();
    syncRounds();
    rebuildFromPicks();
    st.ready = true;
    mount();
    render();
    console.log('[MFF/yahoo-draft] ready —', Object.keys(st.pool).length, 'players,',
      st.board.length, 'board entries,', takenCount(), 'picks backfilled,',
      st.mode, '·', st.scoringLabel, '·', st.slots.teams + 'tm x', st.slots.rounds, 'rds');
  }).catch((e) => console.warn('[MFF/yahoo-draft] boot failed:', e));

  window.__mffYahooDraft = { state: st, recommend, recommendPicks, handleFrame, render, needPositions, adpTag };
})();
