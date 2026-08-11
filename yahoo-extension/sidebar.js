// MFF Yahoo Helper — season-mode sidebar for football.fantasysports.yahoo.com.
// Port of the Sleeper/ESPN helpers' SEASON personality onto Yahoo, whose web
// app exposes no cookie-auth JSON API (the official API is OAuth-only) — so
// the roster comes from scraping the team page's own DOM (`.ysf-player-name`
// rows, stable Yahoo markup for years), the same play the Underdog helper
// runs. probe.js records whatever internal endpoints Yahoo's pages DO call,
// which is the upgrade path to an API-driven v2.
//
// What needs the DOM vs what doesn't:
//   - roster + current starters + slots: scraped from YOUR team page
//     (persisted per league, so other pages keep working)
//   - free agents: captured from the league's Players page as you browse it
//     (rows with an owning-team link are skipped as taken)
//   - everything else (Jack's live boards, KTC, Clay projections, Vegas
//     lines + weekly props, Sleeper injuries/actuals/trending): same open
//     endpoints as the other helpers.
(() => {
  'use strict';
  if (window.__mffYahoo) return;

  const URL_WATCH_MS = 1500;
  const SCRAPE_MS = 2500;
  const SEASON_POLL_MS = 60000;
  const INJ_TTL_MS = 12 * 3600 * 1000;
  const PRIOR_GAMES = 6;
  const CLOSE_PPG = 1.5;
  const MOCK = window.__MFF_YAHOO_MOCK || null;

  // ---------- MFF premium gate (mirrors the Underdog helper's) ----------
  // mff-page-user.js (MAIN world on the MFF site) + mff-bridge.js write the
  // signed-in user + premium flag to chrome.storage 'mff_user' whenever an
  // MFF tab is open. No fresh premium user (24h TTL) = lock screen instead of
  // the panel and the on-page decorators stay off. Harness MOCK bypasses
  // unless window.__MFF_GATE_TEST forces the gate on for testing.
  const GATE_TTL_MS = 24 * 60 * 60 * 1000;
  let _gateUser = null;
  function gateAllowed() {
    if (MOCK && !window.__MFF_GATE_TEST) return true;
    const u = _gateUser;
    return !!(u && u.premium && u.syncedAt && (Date.now() - u.syncedAt) < GATE_TTL_MS);
  }
  function gateLockHTML() {
    const u = _gateUser;
    const signed = !!(u && u.email);
    return '<div style="padding:26px 16px;text-align:center;font-size:12px;line-height:1.5;color:#e5e7eb">' +
      '<div style="font-size:26px">\ud83d\udd12</div>' +
      '<div style="font-weight:800;font-size:13px;margin:6px 0">MFF YAHOO HELPER — Premium</div>' +
      '<div style="color:#9aa0ab;margin-bottom:10px">' + (signed
        ? 'Signed in as ' + String(u.email).replace(/[&<>"]/g, '') + ' — a Premium account is required.'
        : 'Sign in at myfantasyfootball.co with a Premium account to unlock.') + '</div>' +
      '<a href="https://www.myfantasyfootball.co" target="_blank" rel="noopener noreferrer" style="display:inline-block;background:#7d2eff;color:#fff;border-radius:6px;padding:7px 14px;font-weight:700;text-decoration:none;font-size:12px">' +
      (signed ? 'Get Premium' : 'Open MyFantasyFootball') + '</a>' +
      '<div style="color:#6b7280;font-size:10px;margin-top:10px">Unlocks automatically once Premium is active — just open the site while signed in.</div></div>';
  }
  function gateInit(onChange) {
    try {
      chrome.storage.local.get(['mff_user'], (res) => {
        _gateUser = (res && res.mff_user) || null;
        onChange();
      });
      chrome.storage.onChanged.addListener((ch, area) => {
        if (area !== 'local' || !ch.mff_user) return;
        _gateUser = ch.mff_user.newValue || null;
        onChange();
      });
      setInterval(onChange, 60 * 1000); // TTL can lapse without a storage event
    } catch (_) { onChange(); }
  }
  window.__mffGate = { allowed: gateAllowed, set: (u) => { _gateUser = u; } };

  const state = {
    players: [],
    byName: Object.create(null),      // "norm|POS" -> player
    byNameLoose: Object.create(null), // "norm" -> player (best rank wins)
    tiers: {},   // Jack's tier boundaries per rank field: {rank/jSf/jDy/jDsf: [{a,l,n}]}
    exportedAt: '',
    leagueId: null,
    teamName: '',
    seasonSlots: null,   // starter slot labels from the scraped team page
    roster: [],          // [{name,pos,team,slotLbl,starting,inj,p,key}]
    rosterTs: 0,
    faSeen: {},          // key -> 1, captured from the Players page
    myKeys: new Set(),
    mode: 're_1qb',
    modeManual: false,
    modeDetected: null,
    scoringLabel: '½PPR',
    scoringPrefs: { rec: 0.5, passTd: 4 },
    scoringManual: false, // user touched the SETTINGS chips — API stops overriding
    apiSlots: null,       // starter slots from the league settings API (authoritative)
    apiScoring: false,    // scoring was read from the league settings API
    leagueScoring: null,
    seasonWeek: 1,
    byesActive: false,
    nflState: null,
    slMeta: {},          // sid -> {n,pos,tm,inj} from Sleeper /players/nfl
    schedule: {},        // TEAM -> wk -> {opp,home,total,implied}
    wkPropsAll: null,
    seasonStats: null,
    trendAdds: {},
    seasonTab: 'lineup',
    seasonPosFilter: 'ALL',
    seasonTeamSrc: 'ktc',
    expandedKey: null,
    seasonStatus: 'Loading players…',
    probeCount: 0,
    pollTimer: null,
    scrapeTimer: null,
  };

  // ---------- name matching (mirrors export_sleeper_extension_data.py) ----------
  function norm(n) {
    let s = (n || '').toLowerCase().trim();
    for (const suf of [' jr.', ' jr', ' sr.', ' sr', ' iii', ' ii', ' iv', ' v']) {
      if (s.endsWith(suf)) s = s.slice(0, -suf.length).trim();
    }
    s = s.replace(/['’`]/g, '').replace(/[.,]/g, '').replace(/-/g, ' ');
    return s.replace(/\s+/g, ' ').trim();
  }
  function keyOf(p) { return norm(p.n) + '|' + p.s; }

  // Yahoo spells some players differently than the site board (Yahoo says
  // "Kenny Gainwell", the board says "Kenneth Gainwell") — with no alias step
  // the scraped roster row can't match, so the player shows no ranks/pills.
  // Mirrors ALIASES in export_sleeper_extension_data.py, applied in BOTH
  // directions so either spelling resolves.
  const ALIAS_PAIRS = [
    ['kenneth gainwell', 'kenny gainwell'],
    ['kenneth walker', 'ken walker'],
    ['cameron ward', 'cam ward'],
    ['chigoziem okonkwo', 'chig okonkwo'],
    ['marquise brown', 'hollywood brown'],
    ['joshua palmer', 'josh palmer'],
    ['dj moore', 'd j moore'],
  ];
  const ALIASES = Object.create(null);
  for (const [a, b] of ALIAS_PAIRS) {
    (ALIASES[a] || (ALIASES[a] = [])).push(b);
    (ALIASES[b] || (ALIASES[b] = [])).push(a);
  }
  // Name → site player. The loose fallback stays position-guarded: Yahoo's
  // scraped rows always carry a position, so a same-name different-position
  // hit is wrong rather than better-than-nothing.
  function findPlayer(name, pos) {
    const tryName = (nm) => {
      const exact = state.byName[nm + '|' + pos];
      if (exact) return exact;
      const loose = state.byNameLoose[nm];
      return loose && (!pos || loose.s === pos) ? loose : null;
    };
    const nm = norm(name);
    const p = tryName(nm);
    if (p) return p;
    for (const alt of ALIASES[nm] || []) {
      const q = tryName(alt);
      if (q) return q;
    }
    return null;
  }

  // ---------- storage (falls back to memory in the mock harness) ----------
  const mem = {};
  const store = {
    get(keys) {
      return new Promise((res) => {
        try { chrome.storage.local.get(keys, res); } catch (e) { res(mem); }
      });
    },
    set(obj) {
      Object.assign(mem, obj);
      try { chrome.storage.local.set(obj); } catch (e) {}
    },
  };

  // Direct fetch first, background-worker relay if Yahoo's page CSP blocks it.
  function fetchJson(url) {
    return fetch(url).then((r) => {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }).catch((e) => new Promise((resolve, reject) => {
      try {
        chrome.runtime.sendMessage({ type: 'mffFetch', url }, (resp) => {
          if (chrome.runtime.lastError) return reject(e);
          if (!resp || !resp.ok) return reject(new Error(resp ? resp.error : String(e)));
          resolve(resp.data);
        });
      } catch (_) { reject(e); }
    }));
  }

  // ---------- live Jack's boards (Firestore REST sends CORS *) ----------
  const FIRESTORE_URL =
    'https://firestore.googleapis.com/v1/projects/jackb933-website/databases/(default)' +
    '/documents/rankings/jacks-official?key=AIzaSyD9D_Rhb5hEpz2cBWqQr7hcFCDoluwq6uY';
  async function refreshJackBoards() {
    if (MOCK) return;
    try {
      const doc = await fetchJson(FIRESTORE_URL);
      const payload = JSON.parse(doc.fields.data.stringValue);
      const jacks = payload.jacks || {};
      const keyByMode = { superflex: 'jSf', dynasty: 'jDy', dynastysf: 'jDsf', redraft: 'rank' };
      const byNorm = {};
      for (const p of state.players) (byNorm[norm(p.n)] = byNorm[norm(p.n)] || []).push(p);
      let applied = 0;
      for (const [mode, key] of Object.entries(keyByMode)) {
        const order = (jacks[mode] || {})._order || [];
        order.forEach((name, i) => {
          const list = byNorm[norm(name)];
          if (list) for (const p of list) { p[key] = i + 1; applied++; }
        });
        // Jack's ALL-board tier boundaries ride the same doc — keep them in
        // lockstep with the live re-rank above (baked tiers would drift).
        const pt = ((jacks[mode] || {})._posTiers || {}).ALL;
        if (Array.isArray(pt)) {
          state.tiers[key] = pt
            .filter(t => t && t.afterRank >= 1 && t.label)
            .map(t => ({ a: t.afterRank, l: String(t.label), n: String(t.name || '') }))
            .sort((x, y) => x.a - y.a);
        }
      }
      if (applied) {
        const upd = doc.fields.updatedAt ? doc.fields.updatedAt.stringValue.slice(0, 10) : '';
        state.seasonStatus = state.players.length + ' players · boards live' + (upd ? ' ' + upd : '');
        render();
      }
    } catch (e) { /* baked boards from players.json stay in effect */ }
  }

  // v0.2.5: long-lived tabs never re-fetched boards — re-pull when the tab is
  // refocused after 5+ minutes hidden ("saved on the site, came back here").
  let _boardsFetchedAt = Date.now();
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState !== 'visible') return;
    if (Date.now() - _boardsFetchedAt < 5 * 60 * 1000) return;
    _boardsFetchedAt = Date.now();
    refreshJackBoards();
  });

  // ---------- live Vegas overlay + schedule (GitHub Pages sends CORS *) ----------
  function applyLiveVegas(gameTotals) {
    const SOS = window.MFF_PLAYOFF_SOS;
    if (!SOS || !gameTotals) return 0;
    let updated = 0;
    Object.keys(SOS).forEach((team) => {
      const posMap = SOS[team] || {};
      Object.keys(posMap).forEach((pos) => {
        Object.keys(posMap[pos] || {}).forEach((wk) => {
          const rec = posMap[pos][wk];
          if (!rec || !rec.opp) return;
          const key = rec.home ? ('W' + wk + '_' + rec.opp + '_' + team)
                               : ('W' + wk + '_' + team + '_' + rec.opp);
          const g = gameTotals[key];
          if (!g) return;
          if (typeof g.total === 'number') rec.gameTotal = g.total;
          if (typeof g.spread === 'number') {
            rec.teamSpread = rec.home ? g.spread : -g.spread;
            if (typeof g.total === 'number') rec.impliedTotal = (g.total - rec.teamSpread) / 2;
          }
          updated++;
        });
      });
    });
    return updated;
  }
  function buildSchedule(gameTotals) {
    if (!gameTotals) return;
    const sched = {};
    for (const key of Object.keys(gameTotals)) {
      const m = key.match(/^W(\d+)_([A-Z]{2,4})_([A-Z]{2,4})$/);
      if (!m) continue;
      const wk = parseInt(m[1], 10);
      const g = gameTotals[key] || {};
      const total = typeof g.total === 'number' ? g.total : null;
      const hSpread = typeof g.spread === 'number' ? g.spread : null;
      const put = (tm, opp, isHome) => {
        const spread = hSpread == null ? null : (isHome ? hSpread : -hSpread);
        (sched[tm] = sched[tm] || {})[wk] = {
          opp, home: isHome, total,
          implied: (total != null && spread != null)
            ? Math.round(((total - spread) / 2) * 10) / 10 : null,
        };
      };
      put(m[2], m[3], false);
      put(m[3], m[2], true);
    }
    state.schedule = sched;
  }

  // ---------- players.json ----------
  async function loadPlayers() {
    let data;
    if (MOCK && MOCK.players) {
      data = MOCK.players;
    } else {
      const url = chrome.runtime.getURL('data/players.json');
      data = await (await fetch(url)).json();
    }
    state.players = data.players || [];
    state.tiers = data.tiers || {}; // Jack's tier boundaries per rank field
    state.exportedAt = data.exported_at || '';
    for (const p of state.players) {
      const k = keyOf(p);
      if (!state.byName[k]) state.byName[k] = p;
      const loose = norm(p.n);
      if (!state.byNameLoose[loose]) state.byNameLoose[loose] = p;
    }
    applyScoringPrefs();
    state.seasonStatus = state.players.length + ' players · data ' + state.exportedAt;
  }

  // ---------- modes / sources ----------
  const MODES = {
    re_1qb: { label: 'Redraft 1QB' },
    re_sf:  { label: 'Redraft SF' },
    dyn_1qb:{ label: 'Dynasty 1QB' },
    dyn_sf: { label: 'Dynasty SF' },
  };
  const MODE_KEYS = {
    dyn_sf:  { ktc: 'ktcSf',  jack: 'jDsf', fp: 'fpDsf', sl: 'slDsf', adp: 'sa',  vor: 'vorSf', up: 'upSf' },
    dyn_1qb: { ktc: 'ktc1qb', jack: 'jDy',  fp: 'fpDy',  sl: 'slDy',  adp: 'da',  vor: 'vor',   up: 'up'   },
    re_sf:   { ktc: 'ktcSf',  jack: 'jSf',  fp: 'fpSf',  sl: 'slSf',  adp: 'sfa', vor: 'vorSf', up: 'upSf' },
    re_1qb:  { ktc: 'ktc1qb', jack: 'rank', fp: 'fpR',   sl: 'slR',   adp: 'a',   vor: 'vor',   up: 'up'   },
  };
  function modeKeys() { return MODE_KEYS[state.mode] || MODE_KEYS.re_1qb; }
  // Redraft leagues have no use for dynasty tooling — KTC values (a dynasty
  // trade market) disappear everywhere unless the dynasty mode is on.
  function isDynMode() { return state.mode.indexOf('dyn') === 0; }
  // ---------- Jack's board tiers ----------
  // state.tiers[field] = sorted [{a, l, n}] boundaries on that board (from
  // players.json, live-refreshed by refreshJackBoards). A tier applies from
  // rank `a` until the next boundary — same as the site's _tierLabelForRank.
  // Color cycle is the site's .myrank-num tier-X palette (styles/main.css).
  const JACK_TIER_LABELS = ['S','A','B','C','D','E','F','G','H','I','J','K','L','M','N','O','P','Q','R','T','U','V','W','X','Y','Z'];
  const JACK_TIER_COLORS = ['#eab308','#ef4444','#3b82f6','#22c55e','#a855f7','#f97316','#9ca3af','#ec4899','#06b6d4','#84cc16','#f43f5e','#6366f1','#fbbf24','#14b8a6','#d946ef','#ea580c','#38bdf8','#a3e635','#fb7185'];
  function jackTierColor(label) {
    const i = JACK_TIER_LABELS.indexOf(label);
    return JACK_TIER_COLORS[(i >= 0 ? i : 0) % JACK_TIER_COLORS.length];
  }
  function jackTierList() { return state.tiers[modeKeys().jack] || null; }
  function jackTierFor(rank) {
    const list = jackTierList();
    if (!list || !list.length || rank == null) return null;
    let cur = null;
    for (const t of list) { if (t.a <= rank) cur = t; else break; }
    return cur;
  }
  const SOURCES = {
    ktc:  { label: 'KTC',          get: (p) => p[modeKeys().ktc],  desc: true },
    jack: { label: "Jack's Rank",  get: (p) => p[modeKeys().jack], desc: false },
    fp:   { label: 'FantasyPros',  get: (p) => p[modeKeys().fp],   desc: false },
    sl:   { label: 'Sleeper Rank', get: (p) => p[modeKeys().sl],   desc: false },
  };
  // ---------- MY RANKS rank source (user's own site boards) ----------
  // mff-page-user.js ships versionBoards.mine via the bridge into
  // chrome.storage 'mff_my_rankings'. Selecting "My Ranks" makes the ENTIRE
  // rec engine (board order, tiers, quality fill, depletion schedule) run on
  // the user's custom rankings — same behavior the Underdog helper has.
  let _myRanks = null;
  let _myRanksMaps = {};
  function _myMapFor(modeKey) {
    if (!_myRanks || !_myRanks[modeKey]) return null;
    if (!_myRanksMaps[modeKey]) {
      const m = new Map();
      _myRanks[modeKey].forEach((r, i) => {
        const k = norm(r.n) + '|' + r.s;
        if (!m.has(k)) m.set(k, i + 1);
      });
      _myRanksMaps[modeKey] = m;
    }
    return _myRanksMaps[modeKey];
  }
  function myRanksAvailable() {
    const mk = (state.mode).indexOf('dyn') === 0
      ? (state.mode) : (state.mode);
    return !!(_myRanks && _myRanks[mk] && _myRanks[mk].length);
  }
  SOURCES.mine = {
    label: 'My Ranks',
    get: (p) => { const m = _myMapFor(state.mode); return m ? (m.get(keyOf(p)) || null) : null; },
    desc: false,
  };
  function _applyMyRanks(v) {
    _myRanks = (v && v.boards) || null;
    _myRanksMaps = {};
    try { render(); } catch (_) {}
  }
  try {
    chrome.storage.local.get(['mff_my_rankings'], (res) => _applyMyRanks(res && res.mff_my_rankings));
    chrome.storage.onChanged.addListener((ch, area) => {
      if (area === 'local' && ch.mff_my_rankings) _applyMyRanks(ch.mff_my_rankings.newValue);
    });
  } catch (_) {}

  function applyMode(mode, manual) {
    if (!MODES[mode]) return;
    state.mode = mode;
    if (manual) state.modeManual = true;
  }

  // ---------- league scoring ----------
  // Yahoo's league scoring page isn't scraped (v0.1) — SETTINGS carries the
  // two values that move projections (rec + pass TD; Yahoo defaults ½PPR /
  // 4pt). The K/DST models fall back to their built-in defaults, which ARE
  // Yahoo's default kicker/DST values.
  function applyScoringPrefs() {
    const recPts = state.scoringPrefs.rec != null ? state.scoringPrefs.rec : 0.5;
    const passTd = state.scoringPrefs.passTd != null ? state.scoringPrefs.passTd : 4;
    state.leagueScoring = { rec: recPts, pass_td: passTd };
    state.scoringLabel =
      (recPts === 1 ? 'PPR' : recPts === 0.5 ? '½PPR' : recPts === 0 ? 'STD' : recPts + '/rec') +
      (passTd !== 4 ? ' · ' + passTd + 'pt paTD' : '');
    state.scoringVals = { recPts, passTd };
    for (const p of state.players) {
      if (p.cPts == null || !p.cGm) continue;
      const adj = p.cPts + (recPts - 1) * (p.cRec || 0) + (passTd - 4) * (p.cPtd || 0);
      p.szn = Math.round(adj * 10) / 10;
      p.pPg = Math.round((adj / p.cGm) * 10) / 10;
    }
  }

  // League settings API — the same cookie-auth pub-api call the draft panel
  // uses. Gives the EXACT starting slots and per-stat scoring modifiers, which
  // makes it authoritative over both the DOM slot scrape (which could pick up
  // stray slot-labeled rows elsewhere on the page and invent phantom lineup
  // slots — the "2 QB / 3 DEF optimal lineup" bug) and the manual scoring
  // chips (kept as an override: touching them sets scoringManual).
  async function fetchLeagueSettings(leagueId) {
    if (MOCK && !MOCK.settings) return;
    try {
      const j = MOCK ? MOCK.settings : await (await fetch(
        'https://pub-api.fantasysports.yahoo.com/fantasy/v3/settings/nfl/' + leagueId + '?format=rawjson',
        { credentials: 'include' })).json();
      const svc = (j && (j.service || j)) || {};
      const rp = (svc.settings && svc.settings.roster_positions) || [];
      const slots = [];
      for (const r of rp) {
        const lbl = SLOT_MAP[String(r.position || '').toUpperCase().replace(/\s+/g, '')];
        if (!lbl || lbl === 'BN' || lbl === 'IR') continue;
        const n = parseInt(r.count, 10) || 0;
        for (let i = 0; i < n; i++) slots.push(lbl);
      }
      if (slots.length) {
        state.apiSlots = slots;
        state.seasonSlots = slots;
        const sf = slots.indexOf('SUPER_FLEX') !== -1 || slots.filter((s) => s === 'QB').length >= 2;
        state.modeDetected = 're_' + (sf ? 'sf' : '1qb');
        if (!state.modeManual) applyMode(state.modeDetected, false);
      }
      const cats = (svc.settings && svc.settings.stat_categories) || [];
      let rec = null, passTd = null;
      for (const c of cats) {
        if (c.stat_id === 11) rec = parseFloat(c.stat_modifier) || 0;
        if (c.stat_id === 5) passTd = parseFloat(c.stat_modifier) || 4;
      }
      if (rec != null && !state.scoringManual) {
        state.scoringPrefs = { rec, passTd: passTd != null ? passTd : 4 };
        state.apiScoring = true;
        applyScoringPrefs();
      }
      // Playoff shape for the SIMS tab: team count is explicit; Yahoo doesn't
      // expose playoff_start_week here, so derive it — each playoff round is
      // one week ending at end_week.
      const pt = parseInt(svc.settings && svc.settings.num_playoff_teams, 10);
      if (pt >= 2) state.playoffTeams = pt;
      const endWk = parseInt(svc.end_week, 10);
      if (endWk) {
        const rounds = Math.ceil(Math.log2(state.playoffTeams || 4));
        state.playoffStart = endWk - rounds + 1;
      }
      saveLeagueState();
      render();
      console.log('[MFF/yahoo] league settings read:', slots.length, 'starting slots ·',
        state.scoringLabel, '·', state.modeDetected);
    } catch (e) {
      console.warn('[MFF/yahoo] settings API unavailable, staying on scrape/manual:', e);
    }
  }

  // ---------- Yahoo DOM adapter ----------
  // Team page rows: a table row whose first cell is the lineup slot (QB, WR,
  // W/R/T, BN, IR…) containing a `.ysf-player-name` div — `a` = player name,
  // `span` = "Buf - RB" (+ status tokens). DEF rows name the franchise and
  // carry "- DEF" in the meta. Players outside your league page layout are
  // ignored. Yahoo team abbrevs map onto the site's (WAS → WSH).
  const SLOT_MAP = {
    'QB': 'QB', 'RB': 'RB', 'WR': 'WR', 'TE': 'TE', 'K': 'K',
    'DEF': 'DEF', 'D': 'DEF', 'D/ST': 'DEF', 'DST': 'DEF',
    'W/R': 'WRRB_FLEX', 'W/T': 'REC_FLEX', 'W/R/T': 'FLEX', 'FLEX': 'FLEX',
    'Q/W/R/T': 'SUPER_FLEX', 'OP': 'SUPER_FLEX', 'SF': 'SUPER_FLEX',
    'BN': 'BN', 'IR': 'IR', 'IL': 'IR', 'IR+': 'IR', 'IL+': 'IR',
  };
  const SLOT_ELIG = {
    QB: ['QB'], RB: ['RB'], WR: ['WR'], TE: ['TE'], K: ['K'], DEF: ['DST'],
    FLEX: ['RB', 'WR', 'TE'], SUPER_FLEX: ['QB', 'RB', 'WR', 'TE'],
    WRRB_FLEX: ['WR', 'RB'], REC_FLEX: ['WR', 'TE'],
  };
  function fixAbbr(a) {
    a = String(a || '').toUpperCase();
    return a === 'WAS' ? 'WSH' : a === 'JAC' ? 'JAX' : a;
  }
  function detectLeagueId() {
    if (MOCK && MOCK.leagueId) return MOCK.leagueId;
    const m = location.pathname.match(/\/f1\/(\d+)/);
    return m ? m[1] : null;
  }
  function onPlayersPage() {
    if (MOCK) return !!MOCK.playersPage;
    return /\/f1\/\d+\/players/.test(location.pathname);
  }
  // Team pages are /f1/<league>/<teamId>. Matchup pages ALSO render slot-
  // labeled rosters (both teams'), so scraping is gated to team URLs only.
  function onTeamPage() {
    if (MOCK) return !MOCK.playersPage;
    return /\/f1\/\d+\/\d+(?:$|[?\/])/.test(location.pathname);
  }
  function matchScraped(name, pos, team) {
    if (pos === 'DST') {
      return state.players.find((x) => x.s === 'DST' && x.sTm === team) || null;
    }
    return findPlayer(name, pos);
  }
  function parsePlayerCell(cell) {
    const box = cell.querySelector('.ysf-player-name');
    if (!box) return null;
    const a = box.querySelector('a');
    if (!a) return null;
    const name = a.textContent.trim();
    if (!name) return null;
    // The "Tm - POS" meta is NOT always the first span: D/ST rows on the
    // Players page lead with the "player Notes" status span, so a first-span
    // read came back "No new player Notes", the position never parsed, and
    // no D/ST was ever captured as a free agent. Scan every span in the box
    // (then the whole row) for the pattern instead.
    let mm = null;
    const spanScope = [...box.querySelectorAll('span')];
    const rowEl = cell.closest ? (cell.closest('tr') || cell) : cell;
    for (const sp of spanScope.concat([...rowEl.querySelectorAll('span')])) {
      mm = (sp.textContent || '').trim().match(/([A-Za-z]{2,3})\s*-\s*(QB|WR|RB|TE|K|DEF|D)\b/i);
      if (mm) break;
    }
    const team = mm ? fixAbbr(mm[1]) : '';
    let pos = mm ? mm[2].toUpperCase() : '';
    if (pos === 'DEF' || pos === 'D') pos = 'DST';
    // status: Yahoo renders it as a dedicated status/injury span when present
    let inj = null;
    const stEl = box.querySelector('.ysf-player-status, .F-injury, abbr');
    const st = stEl ? stEl.textContent.trim().toUpperCase() : '';
    if (/^(O|IR|IR-R|PUP|PUP-P|NA|NFI|SUSP|SSPD)/.test(st)) inj = 'OUT';
    else if (st === 'D') inj = 'D';
    else if (st === 'Q') inj = 'Q';
    const p = matchScraped(name, pos, team);
    return {
      name, pos: p ? p.s : (pos || '?'), team: p ? (p.sTm || team) : team, inj,
      p: p || null, key: p ? keyOf(p) : norm(name) + '|' + (pos || '?'),
    };
  }
  // Scrape the CURRENT page's roster table. Returns null when the page has no
  // slot-labeled roster rows (league home, players page, matchups…).
  function scrapeTeamPage() {
    if (MOCK && MOCK.noScrape) return null;
    if (!onTeamPage()) return null;
    // Scope to the roster stat tables when the classic layout provides them
    // (#statTable0 offense / 1 kickers / 2 defense) — a page-wide <tr> sweep
    // can catch slot-labeled rows from other modules and invent lineup slots.
    const scoped = document.querySelectorAll('table[id^="statTable"] tr');
    const rows = scoped.length ? scoped : document.querySelectorAll('tr');
    const entries = [];
    const slots = [];
    for (const row of rows) {
      const cells = row.querySelectorAll('td');
      if (cells.length < 2) continue;
      const slotTok = cells[0].textContent.trim().toUpperCase().replace(/\s+/g, '');
      const slotLbl = SLOT_MAP[slotTok];
      if (!slotLbl) continue;
      const info = parsePlayerCell(row);
      if (slotLbl !== 'BN' && slotLbl !== 'IR') slots.push(slotLbl);
      if (!info) continue; // empty roster slot — still counts toward lineup slots
      entries.push(Object.assign(info, { slotLbl, starting: slotLbl !== 'BN' && slotLbl !== 'IR' }));
    }
    if (!slots.length || !entries.length) return null;
    // team name: Yahoo puts it in the page's team header link/title
    let teamName = '';
    const th = document.querySelector('#team-card-info a, .Navtarget, h1');
    if (th) teamName = th.textContent.trim().slice(0, 40);
    return { entries, slots, teamName };
  }
  // Players-page capture: any player row WITHOUT an owning-team link on the
  // row is treated as available. Accumulates as the user pages/filters.
  function scrapePlayersPage() {
    if (!onPlayersPage()) return 0;
    const lid = state.leagueId;
    let added = 0;
    const rows = document.querySelectorAll('tr');
    for (const row of rows) {
      const info = parsePlayerCell(row);
      if (!info || !info.p) continue;
      if (state.myKeys.has(info.key)) continue;
      const ownerLink = [...row.querySelectorAll('a')].some((a) => {
        const m = a.getAttribute('href') && a.getAttribute('href').match(/\/f1\/(\d+)\/(\d+)(?:$|[/?])/);
        return m && m[1] === lid;
      });
      if (ownerLink) { delete state.faSeen[info.key]; continue; } // taken
      if (!state.faSeen[info.key]) { state.faSeen[info.key] = 1; added++; }
      if (info.inj) state.scrapedInj[info.key] = info.inj;
    }
    if (added) saveLeagueState();
    return added;
  }
  state.scrapedInj = Object.create(null);
  function applyScrapedRoster(scr) {
    state.roster = scr.entries;
    // The settings API owns the slot list when it answered; scraped slots are
    // the fallback for logged-out / API-failure sessions only.
    state.seasonSlots = state.apiSlots || scr.slots;
    state.rosterTs = Date.now();
    if (scr.teamName) state.teamName = scr.teamName;
    state.myKeys = new Set(scr.entries.map((e) => e.key));
    scr.entries.forEach((e) => { if (e.inj) state.scrapedInj[e.key] = e.inj; });
    if (!state.apiSlots) {
      const sf = scr.slots.indexOf('SUPER_FLEX') !== -1 || scr.slots.filter((s) => s === 'QB').length >= 2;
      state.modeDetected = 're_' + (sf ? 'sf' : '1qb'); // dynasty isn't scrapable — user overrides
      if (!state.modeManual) applyMode(state.modeDetected, false);
    }
    saveLeagueState();
  }
  function saveLeagueState() {
    if (!state.leagueId) return;
    store.set({
      ['yahooLeague_' + state.leagueId]: {
        ts: state.rosterTs,
        teamName: state.teamName,
        slots: state.seasonSlots,
        entries: state.roster.map((e) => ({
          name: e.name, pos: e.pos, team: e.team, slotLbl: e.slotLbl,
          starting: e.starting, inj: e.inj || null,
        })),
        faSeen: state.faSeen,
        mode: state.mode,
        modeManual: state.modeManual,
        scoringPrefs: state.scoringPrefs,
        scoringManual: state.scoringManual,
        tab: state.seasonTab,
        posFilter: state.seasonPosFilter,
        teamSrc: state.seasonTeamSrc,
      },
    });
  }
  function restoreLeagueState(saved) {
    if (!saved) return;
    if (Array.isArray(saved.entries) && saved.entries.length) {
      state.roster = saved.entries.map((e) => {
        const p = matchScraped(e.name, e.pos === 'DST' ? 'DST' : e.pos, e.team);
        return {
          name: e.name, pos: p ? p.s : e.pos, team: e.team, slotLbl: e.slotLbl,
          starting: !!e.starting, inj: e.inj || null,
          p: p || null, key: p ? keyOf(p) : norm(e.name) + '|' + e.pos,
        };
      });
      state.myKeys = new Set(state.roster.map((e) => e.key));
      state.roster.forEach((e) => { if (e.inj) state.scrapedInj[e.key] = e.inj; });
      state.rosterTs = saved.ts || 0;
    }
    if (Array.isArray(saved.slots) && saved.slots.length) state.seasonSlots = saved.slots;
    if (saved.teamName) state.teamName = saved.teamName;
    if (saved.faSeen) state.faSeen = saved.faSeen;
    if (saved.mode && MODES[saved.mode]) { state.mode = saved.mode; state.modeManual = !!saved.modeManual; }
    if (saved.scoringPrefs) { state.scoringPrefs = saved.scoringPrefs; state.scoringManual = !!saved.scoringManual; applyScoringPrefs(); }
    if (saved.tab) state.seasonTab = saved.tab;
    if (saved.posFilter) state.seasonPosFilter = saved.posFilter;
    if (saved.teamSrc && SOURCES[saved.teamSrc]) state.seasonTeamSrc = saved.teamSrc;
  }

  // ---------- open-data feeds (Sleeper public API) ----------
  async function ensureNflState() {
    if (state.nflState) return;
    if (MOCK && MOCK.nflState) {
      state.nflState = MOCK.nflState;
    } else {
      try { state.nflState = (await fetchJson('https://api.sleeper.app/v1/state/nfl')) || {}; }
      catch (e) { state.nflState = {}; }
    }
    const nfl = state.nflState;
    const wk = nfl && nfl.season_type === 'regular' ? nfl.week : null;
    state.seasonWeek = wk && wk >= 1 ? wk : 1;
    state.byesActive = !!(nfl && nfl.season_type === 'regular');
  }
  async function fetchInjuries() {
    if (MOCK) { state.slMeta = MOCK.slMeta || {}; return; }
    try {
      const saved = await store.get(['yahooHelper.slMeta']);
      const cached = saved['yahooHelper.slMeta'];
      if (cached && cached.ts && Date.now() - cached.ts < INJ_TTL_MS) {
        state.slMeta = cached.map || {};
        render();
        return;
      }
    } catch (e) {}
    try {
      const all = await fetchJson('https://api.sleeper.app/v1/players/nfl');
      const map = {};
      const OUT_STATUS = /^(Injured Reserve|Physically Unable|Non Football|Suspended|Reserve)/i;
      const KEEP = { QB: 1, RB: 1, WR: 1, TE: 1, K: 1, DST: 1 };
      for (const sid of Object.keys(all || {})) {
        const pl = all[sid];
        if (!pl) continue;
        const pos = pl.position === 'DEF' ? 'DST' : pl.position;
        if (!KEEP[pos]) continue;
        let inj = null;
        const is = pl.injury_status || '';
        if (/^(Out|IR|PUP|COV|Sus|NA|DNR)/i.test(is) || OUT_STATUS.test(pl.status || '')) inj = 'OUT';
        else if (/^Doubtful/i.test(is)) inj = 'D';
        else if (/^Questionable/i.test(is)) inj = 'Q';
        const entry = { n: ((pl.first_name || '') + ' ' + (pl.last_name || '')).trim(), pos, tm: pl.team || '' };
        if (inj) entry.inj = inj;
        map[sid] = entry;
      }
      state.slMeta = map;
      store.set({ 'yahooHelper.slMeta': { ts: Date.now(), map } });
      render();
    } catch (e) { /* flags just stay off */ }
  }
  async function fetchSeasonStats() {
    if (MOCK) return;
    if (!state.byesActive || state.seasonWeek <= 1) return;
    const upTo = state.seasonWeek - 1;
    const season = (state.nflState && state.nflState.season) || '2026';
    try {
      const saved = await store.get(['yahooHelper.seasonStats']);
      const c = saved['yahooHelper.seasonStats'];
      if (c && c.season === season && c.upToWk === upTo && Date.now() - c.ts < 6 * 3600 * 1000) {
        state.seasonStats = c;
        render();
        return;
      }
    } catch (e) {}
    try {
      const byId = {};
      for (let wk = 1; wk <= upTo; wk++) {
        const stats = await fetchJson('https://api.sleeper.app/v1/stats/nfl/regular/' + season + '/' + wk);
        if (!stats) continue;
        for (const sid of Object.keys(stats)) {
          const s = stats[sid];
          if (!s || !s.gp) continue;
          const rec = byId[sid] || (byId[sid] = { ppr: 0, half: 0, std: 0, gp: 0 });
          rec.ppr += s.pts_ppr || 0;
          rec.half += s.pts_half_ppr || 0;
          rec.std += s.pts_std || 0;
          rec.gp += 1;
        }
      }
      state.seasonStats = { ts: Date.now(), season, upToWk: upTo, byId };
      store.set({ 'yahooHelper.seasonStats': state.seasonStats });
      render();
    } catch (e) { /* preseason projections just stand */ }
  }
  function actualPpgFor(p) {
    const st = state.seasonStats;
    const rec = st && p.sid && st.byId[p.sid];
    if (!rec || !rec.gp) return null;
    const recPts = (state.scoringVals && state.scoringVals.recPts != null) ? state.scoringVals.recPts : 1;
    const total = recPts >= 0.75 ? rec.ppr : recPts <= 0.25 ? rec.std : rec.half;
    return { ppg: total / rec.gp, gp: rec.gp };
  }
  async function fetchTrending() {
    if (MOCK) { state.trendAdds = MOCK.trendAdds || {}; return; }
    try {
      const t = await fetchJson('https://api.sleeper.app/v1/players/nfl/trending/add?lookback_hours=24&limit=50');
      state.trendAdds = {};
      if (Array.isArray(t)) for (const x of t) state.trendAdds[String(x.player_id)] = x.count;
    } catch (e) {}
  }

  // ---------- weekly value ----------
  function onByeThisWeek(p) {
    if (!state.byesActive) return false;
    if (p.bye != null) return p.bye === state.seasonWeek;
    const sch = p.sTm && state.schedule[p.sTm];
    return !!(sch && Object.keys(sch).length >= 8 && !sch[state.seasonWeek]);
  }
  function injOf(p) {
    const k = keyOf(p);
    if (state.scrapedInj[k]) return state.scrapedInj[k]; // Yahoo's own flag is freshest
    const m = p.sid && state.slMeta[p.sid];
    return (m && m.inj) || null;
  }
  function propsProjFor(p) {
    const all = state.wkPropsAll;
    if (!all || p._unmatched) return null;
    const wk = String(state.seasonWeek);
    const cacheKey = wk + '|' + state.scoringLabel;
    if (p._wkpKey === cacheKey) return p._wkpVal;
    if (!state._wkPropsIdx || state._wkPropsIdx.wk !== wk) {
      const map = {};
      const block = all[wk] || {};
      for (const nm of Object.keys(block)) map[norm(nm)] = block[nm];
      state._wkPropsIdx = { wk, map };
    }
    const rec = state._wkPropsIdx.map[norm(p.n)];
    let out = null;
    const books = rec ? [rec.UD, rec.PP].filter(Boolean) : [];
    if (books.length) {
      const avg = (k) => {
        const vs = books.map((b) => b[k]).filter((v) => typeof v === 'number');
        return vs.length ? vs.reduce((a, b) => a + b, 0) / vs.length : null;
      };
      const py = avg('py'), ry = avg('ry'), rcy = avg('rcy');
      if (py != null || ry != null || rcy != null) {
        const sv = state.scoringVals || { recPts: 0.5, passTd: 4 };
        let pts = 0;
        if (py != null) {
          const ptd = avg('ptd');
          pts += py * 0.04 + (ptd != null ? ptd : py / 125) * (sv.passTd != null ? sv.passTd : 4);
          const ints = avg('int');
          if (ints != null) pts -= ints;
        }
        if (ry != null) pts += ry * 0.1;
        if (rcy != null) {
          pts += rcy * 0.1;
          const recEst = rcy / (p.s === 'RB' ? 7.5 : 11.5);
          pts += recEst * (sv.recPts != null ? sv.recPts : 0.5);
        }
        const atd = avg('atd');
        if (atd != null) {
          const prob = atd < 0 ? -atd / (-atd + 100) : 100 / (atd + 100);
          pts += prob * (p.s === 'QB' ? 1 : 1.1) * 6;
        }
        out = Math.round(pts * 10) / 10;
      }
    }
    p._wkpKey = cacheKey;
    p._wkpVal = out;
    return out;
  }
  function wkOppInfo(p) {
    const g = p.sTm && state.schedule[p.sTm] && state.schedule[p.sTm][state.seasonWeek];
    if (!g) return null;
    let val = g.implied, good, bad;
    if (p.s === 'DST') {
      val = (g.total != null && g.implied != null) ? Math.round((g.total - g.implied) * 10) / 10 : null;
      good = val != null && val <= 20.5;
      bad = val != null && val >= 25.5;
    } else {
      good = val != null && val >= 26;
      bad = val != null && val <= 20.5;
    }
    const col = good ? ['#2a4030', '#6dd06d'] : bad ? ['#402a2a', '#d06d6d'] : ['#2a2c33', '#c8ccd4'];
    const txt = (g.home ? 'vs' : '@') + g.opp;
    return {
      txt, bg: col[0], fg: col[1],
      tip: 'Wk ' + state.seasonWeek + ' ' + txt +
        (g.total != null ? ' · O/U ' + g.total : '') +
        (g.implied != null ? ' · implied ' + g.implied : '') +
        (p.s === 'DST' && val != null ? ' · opp implied ' + val : ''),
    };
  }
  function wkOppHTML(p) {
    const g = wkOppInfo(p);
    if (!g) return '';
    return `<span class="tag" style="background:${g.bg};color:${g.fg}" title="${esc(g.tip)}">${esc(g.txt)}</span>`;
  }
  // K/DST models — verbatim from the Sleeper/ESPN helpers. The built-in
  // defaults ARE Yahoo's default kicker/DST scoring, so they hold even with
  // no scraped scoring rules.
  const FG_MIX_AVG = [0.02, 0.22, 0.30, 0.30, 0.16];
  const FG_KEYS = ['fgm_0_19', 'fgm_20_29', 'fgm_30_39', 'fgm_40_49', 'fgm_50p'];
  const FG_DEF_PTS = [3, 3, 3, 4, 5];
  function kickerProjFor(p, g) {
    const T = g && g.implied != null ? g.implied : 22.5;
    if (p.kFga == null) return 5 + (T - 22.5) * 0.3;
    const gm = p.cGm || 17;
    const fgScale = (0.036 * T + 0.74) / 1.55;
    const xpScale = Math.max(0.2, (0.115 * T - 0.29) / 2.3);
    const fgm = (p.kFgm / gm) * fgScale;
    const fga = (p.kFga / gm) * fgScale;
    const xpm = ((p.kXpm != null ? p.kXpm : p.kFgm * 1.3) / gm) * xpScale;
    const xpa = ((p.kXpa != null ? p.kXpa : p.kXpm || 0) / gm) * xpScale;
    const sc = state.leagueScoring || {};
    const mix = (p.kD && p.kD.length === 5) ? p.kD : FG_MIX_AVG;
    let pts = 0;
    for (let i = 0; i < 5; i++) {
      pts += fgm * mix[i] * (sc[FG_KEYS[i]] != null ? sc[FG_KEYS[i]] : FG_DEF_PTS[i]);
    }
    pts += xpm * (sc.xpm != null ? sc.xpm : 1);
    if (sc.fgmiss) pts += (fga - fgm) * sc.fgmiss;
    if (sc.xpmiss) pts += Math.max(0, xpa - xpm) * sc.xpmiss;
    return pts;
  }
  const PA_BUCKETS = [
    ['pts_allow_0', -0.5, 0.5, 10],
    ['pts_allow_1_6', 0.5, 6.5, 7],
    ['pts_allow_7_13', 6.5, 13.5, 4],
    ['pts_allow_14_20', 13.5, 20.5, 1],
    ['pts_allow_21_27', 20.5, 27.5, 0],
    ['pts_allow_28_34', 27.5, 34.5, -1],
    ['pts_allow_35p', 34.5, 99.5, -4],
  ];
  function dstProjFor(p, g) {
    const O = g && g.total != null && g.implied != null ? g.total - g.implied : 22.5;
    const sc = state.leagueScoring || {};
    const val = (k, d) => (sc[k] != null ? sc[k] : d);
    const q = p.dRk != null ? 1 + (16.5 - p.dRk) * 0.012 : 1;
    const sacks = Math.max(0.5, 3.6 - 0.055 * O) * q;
    const ints = Math.max(0.2, 1.5 - 0.025 * O) * q;
    const dtd = Math.max(0.05, 0.28 - 0.005 * O) * q;
    let pts = sacks * val('sack', 1) + ints * val('int', 2) + 0.5 * q * val('fum_rec', 2) +
      dtd * val('def_td', 6) + 0.06 * q * val('safe', 2) + 0.07 * q * val('blk_kick', 2);
    if (sc.ff) pts += 0.85 * q * sc.ff;
    const cdf = (x) => 1 / (1 + Math.exp(-(x - O) / 5.6));
    for (let i = 0; i < PA_BUCKETS.length; i++) {
      const b = PA_BUCKETS[i];
      pts += (cdf(b[2]) - cdf(b[1])) * val(b[0], b[3]);
    }
    return pts;
  }
  function wkVal(p) {
    if (onByeThisWeek(p)) return 0;
    const act = actualPpgFor(p);
    const shrink = act ? act.gp / (act.gp + PRIOR_GAMES) : 0;
    let v;
    if (p.s === 'K' || p.s === 'DST') {
      const g = p.sTm && state.schedule[p.sTm] && state.schedule[p.sTm][state.seasonWeek];
      v = p.s === 'K' ? kickerProjFor(p, g) : dstProjFor(p, g);
      if (act) {
        const prior = p.s === 'K' ? (p.pPg != null ? p.pPg : 7.5) : dstProjFor(p, null);
        v += (act.ppg - prior) * shrink;
      }
      v = Math.max(1, v);
    } else {
      let base = p.pPg != null ? p.pPg : 0;
      if (act) base += (act.ppg - base) * shrink;
      v = base;
      const props = propsProjFor(p);
      if (props != null) v = (p.pPg != null || act) ? 0.8 * props + 0.2 * base : props;
    }
    const inj = injOf(p);
    if (inj) {
      if (inj === 'OUT') return 0;
      if (inj === 'D') v *= 0.3;
      else if (inj === 'Q') v *= 0.85;
    }
    if (v > 0 && p.rank != null && !p._unmatched && p.s !== 'K' && p.s !== 'DST') {
      v += Math.max(-0.67, Math.min(1, (100 - p.rank) / 100)) * 1.5;
      if (v < 0) v = 0;
    }
    return Math.round(v * 100) / 100;
  }

  // ---------- lineup / waivers (identity = keyOf) ----------
  function myPlayerObjs() {
    return state.roster.map((en) => en.p ||
      { n: en.name, s: en.pos || '?', sTm: en.team, rank: 9999, _unmatched: true });
  }
  function currentStarterKeys() {
    return new Set(state.roster.filter((en) => en.starting).map((en) => en.key));
  }
  function optimalLineup(pool) {
    const slots = state.seasonSlots || [];
    const order = slots.map((s, i) => ({ s, i, w: SLOT_ELIG[s] ? SLOT_ELIG[s].length : 99 }))
      .sort((a, b) => a.w - b.w);
    const entries = pool.map((p) => ({ p, v: wkVal(p) }))
      .sort((a, b) => b.v - a.v || ((a.p.rank || 9999) - (b.p.rank || 9999)));
    const used = new Set();
    const byIdx = {};
    let total = 0;
    for (const o of order) {
      const elig = SLOT_ELIG[o.s];
      if (!elig) { byIdx[o.i] = null; continue; }
      const e = entries.find((x) => !used.has(x) && elig.indexOf(x.p.s) !== -1);
      if (e) { used.add(e); byIdx[o.i] = e; total += e.v; }
      else byIdx[o.i] = null;
    }
    return {
      assign: slots.map((s, i) => ({ slot: s, e: byIdx[i] || null })),
      total: Math.round(total * 10) / 10,
    };
  }
  function lineupMoves(opt, starterSet, pool) {
    const adds = opt.assign
      .filter((a) => a.e && !starterSet.has(keyOf(a.e.p)))
      .map((a) => a.e)
      .sort((a, b) => b.v - a.v);
    const optKeys = new Set(opt.assign.filter((a) => a.e).map((a) => keyOf(a.e.p)));
    const sits = pool.filter((p) => starterSet.has(keyOf(p)) && !optKeys.has(keyOf(p)))
      .map((p) => ({ p, v: wkVal(p) }))
      .sort((a, b) => a.v - b.v);
    const usedSit = new Set();
    return adds.map((add) => {
      const sit = sits.find((s) => !usedSit.has(s) && s.p.s === add.p.s) ||
                  sits.find((s) => !usedSit.has(s)) || null;
      if (sit) usedSit.add(sit);
      return { add, sit, delta: sit ? Math.round((add.v - sit.v) * 10) / 10 : null };
    });
  }
  function seasonLineupCalc() {
    if (!state.roster.length || !state.seasonSlots) return null;
    const pool = myPlayerObjs();
    const opt = optimalLineup(pool);
    const starterSet = currentStarterKeys();
    const moves = lineupMoves(opt, starterSet, pool);
    const cls = {};
    for (const mv of moves) {
      if (mv.sit && mv.delta != null && Math.abs(mv.delta) < CLOSE_PPG) {
        cls[keyOf(mv.add.p)] = 'close';
        cls[keyOf(mv.sit.p)] = 'close';
      } else {
        cls[keyOf(mv.add.p)] = 'go';
        if (mv.sit) cls[keyOf(mv.sit.p)] = 'sit';
      }
    }
    return { pool, opt, starterSet, moves, cls };
  }
  // Yahoo can't enumerate league-mates' rosters over the DOM, so the FA pool
  // is what the user has BROWSED on the league's Players page (rows without
  // an owner link), accumulated per league.
  function freeAgents() {
    // `p.ir` = the site's OUT FOR SEASON flag. Never surface one as a free
    // agent worth adding; dynasty keeps them, matching the site's split.
    return state.players.filter((p) => state.faSeen[keyOf(p)] && !state.myKeys.has(keyOf(p)) &&
      !(p.ir && !isDynMode()));
  }
  function waiverRecs() {
    const mine = myPlayerObjs();
    const base = optimalLineup(mine).total;
    const dyn = state.mode.indexOf('dyn') === 0;
    const mk = modeKeys();
    const fas = freeAgents().filter(
      (p) => state.seasonPosFilter === 'ALL' || p.s === state.seasonPosFilter
    );
    const scored = fas.map((p) => {
      const delta = Math.round((optimalLineup(mine.concat([p])).total - base) * 10) / 10;
      const trend = (p.sid && state.trendAdds[p.sid]) || 0;
      let score = delta * 4 + (p.pPg || 0) * 0.6;
      if (dyn && p[mk.ktc] != null) score += p[mk.ktc] / 400;
      if (trend) score += Math.min(3, Math.log10(trend + 1) * 1.5);
      return { p, delta, trend, score: Math.round(score * 10) / 10 };
    });
    scored.sort((a, b) => b.score - a.score);
    return scored.slice(0, 25);
  }
  function dropCandidates() {
    const mine = myPlayerObjs();
    const base = optimalLineup(mine).total;
    const dyn = state.mode.indexOf('dyn') === 0;
    const mk = modeKeys();
    const slots = state.seasonSlots || [];
    const posCount = {};
    for (const p of mine) posCount[p.s] = (posCount[p.s] || 0) + 1;
    const required = new Set(slots.map((s) => (SLOT_ELIG[s] && SLOT_ELIG[s].length === 1) ? SLOT_ELIG[s][0] : null));
    return mine.map((p) => {
      const marginal = Math.round((base - optimalLineup(mine.filter((x) => x !== p)).total) * 10) / 10;
      let keep = marginal * 4 + (p.pPg || 0);
      if (dyn && !p._unmatched && p[mk.ktc] != null) keep += p[mk.ktc] / 300;
      if (required.has(p.s) && (posCount[p.s] || 0) <= 1) keep += 100;
      return { p, marginal, keep };
    }).sort((a, b) => a.keep - b.keep);
  }

  // ---------- SIMS tab: Monte Carlo season sims (port of the ESPN helper's) ----------
  // Engine + data ride the same bundle (engine_sim.js + data/sim_pack.js);
  // live Vegas lands in window.BETTING_2026 from the site fetch in main().
  // League rosters: Yahoo's pub-api has no fantasy-ownership route, so every
  // team's roster is read the way the EXPORT feature reads them — one
  // same-origin HTML fetch per team page, parsed with the sidebar's own row
  // parser, cached per day. Matchup pairings aren't exposed either, so the
  // sim always runs a synthetic round-robin schedule.
  const SIM_RUNS = 1500, SIM_SEED = 99;
  state.seasonTeams = [];
  state.myTeamId = null;
  state.playoffTeams = 6;
  state.playoffStart = 15;
  state.seasonSim = { leagueId: null, status: 'idle', results: null, placeCounts: null,
    sims: SIM_RUNS, recHash: null, synthPairs: true, note: '', selTeam: null };
  function simAvailable() {
    return !!(window.SimEngine && typeof MIKE_CLAY_PROJ !== 'undefined' &&
      typeof PLAYER_WEEKLY_SIGMA !== 'undefined' && window.BETTING_2026);
  }
  function simEnsureGlobals() {
    if (!window.SIM_SLEEPER) {
      window.SIM_SLEEPER = { players: state.players.filter((p) => p.sid).map((p) => ({
        n: p.n, sid: p.sid, a: p.a, age: p.age, ktc1qb: p.ktc1qb, ktcSf: p.ktcSf })) };
    }
    const meta = {};
    for (const sid of Object.keys(state.slMeta)) {
      const e = state.slMeta[sid];
      if (e.inj) meta[sid] = { inj: e.inj };
    }
    window.SIM_SLEEPER_META = meta;
  }
  function simUnavailable() {
    // Yahoo's slMeta collapses statuses to OUT/D/Q, so season-long vs weekly
    // outs can't be split like ESPN's: league-enforced IR slots sim as gone
    // all season; a weekly OUT flag benches the current week (regular season
    // only); Q/D stay in — the sim's variance owns those.
    const out = {};
    if (state.byesActive) {
      for (const sid of Object.keys(state.slMeta)) {
        if (state.slMeta[sid].inj === 'OUT') out[sid] = 'out';
      }
    }
    state.seasonTeams.forEach((t) => t.entries.forEach((en) => {
      if (!en.p || !en.p.sid) return;
      if (en.slotLbl === 'IR') out[en.p.sid] = 'ir';
      else if (state.byesActive && en.inj === 'OUT' && !out[en.p.sid]) out[en.p.sid] = 'out';
    }));
    return out;
  }
  function simTeams() {
    return state.seasonTeams.map((t) => ({
      rosterId: t.teamId,
      name: t.name,
      playerIds: t.entries.filter((en) => en.p && en.p.sid && en.slotLbl !== 'IR')
        .map((en) => String(en.p.sid)),
      record: null, // Yahoo standings records not parsed yet (preseason anyway)
    }));
  }
  function simRecHash() {
    return state.seasonTeams.map((t) =>
      t.teamId + ':' + t.entries.length).join('|');
  }
  function simRoundRobin(ids, weeks) {
    const arr = ids.slice();
    if (arr.length % 2) arr.push(null);
    const n = arr.length, half = n / 2, pairsByWeek = {};
    weeks.forEach((wk) => {
      const prs = [];
      for (let j = 0; j < half; j++) {
        const a = arr[j], b = arr[n - 1 - j];
        if (a != null && b != null) prs.push({ a, b });
      }
      pairsByWeek[wk] = prs;
      arr.splice(1, 0, arr.pop()); // rotate all but first
    });
    return pairsByWeek;
  }
  function fetchDoc(path) {
    return fetch(path, { credentials: 'include' }).then((r) => r.text())
      .then((t) => new DOMParser().parseFromString(t, 'text/html'));
  }
  function parseRosterDoc(doc) {
    const scoped = doc.querySelectorAll('table[id^="statTable"] tr');
    const rows = scoped.length ? scoped : doc.querySelectorAll('tr');
    const entries = [];
    for (const row of rows) {
      const cells = row.querySelectorAll('td');
      if (cells.length < 2) continue;
      const slotTok = cells[0].textContent.trim().toUpperCase().replace(/\s+/g, '');
      const slotLbl = SLOT_MAP[slotTok];
      if (!slotLbl) continue;
      const info = parsePlayerCell(row);
      if (!info) continue;
      entries.push(Object.assign(info, { slotLbl }));
    }
    return entries;
  }
  function detectMyTeamId(doc) {
    const lid = state.leagueId;
    for (const a of doc.querySelectorAll('a')) {
      if (!/my\s*team/i.test(a.textContent || '')) continue;
      const m = (a.getAttribute('href') || '').match(new RegExp('/f1/' + lid + '/(\\d{1,2})(?:$|[?#/])'));
      if (m) return parseInt(m[1], 10);
    }
    return null;
  }
  let _rostersLoading = false;
  async function fetchLeagueRosters(force) {
    if (MOCK) {
      if (MOCK.seasonTeams) {
        state.seasonTeams = MOCK.seasonTeams;
        if (MOCK.myTeamId != null) state.myTeamId = MOCK.myTeamId;
        if (state.seasonTab === 'sims') setTimeout(ensureSeasonSim, 0);
      }
      return;
    }
    const lid = state.leagueId;
    if (!lid || _rostersLoading) return;
    const day = new Date().toDateString();
    const cacheKey = 'yahooRosters_' + lid;
    if (!force) {
      try {
        const saved = await store.get([cacheKey]);
        const c = saved[cacheKey];
        if (c && c.day === day && Array.isArray(c.teams) && c.teams.length) {
          state.seasonTeams = c.teams.map((t) => ({
            teamId: t.teamId, name: t.name,
            entries: (t.entries || []).map((e) => {
              const p = matchScraped(e.name, e.pos, e.team);
              return { name: e.name, pos: e.pos, team: e.team, slotLbl: e.slotLbl,
                inj: e.inj || null, p: p || null, key: p ? keyOf(p) : norm(e.name) + '|' + e.pos };
            }),
          }));
          if (c.myTeamId != null) state.myTeamId = c.myTeamId;
          if (state.seasonTab === 'sims') setTimeout(ensureSeasonSim, 0);
          render();
          return;
        }
      } catch (e) {}
    }
    _rostersLoading = true;
    try {
      state.seasonStatus = 'Reading league rosters…';
      render();
      const home = await fetchDoc('/f1/' + lid);
      if (state.myTeamId == null) state.myTeamId = detectMyTeamId(home) || detectMyTeamId(document);
      const seen = {}, teams = [];
      home.querySelectorAll('a').forEach((a) => {
        const m = (a.getAttribute('href') || '').match(new RegExp('^/f1/' + lid + '/(\\d{1,2})(?:$|[?#])'));
        if (!m) return;
        const tid = parseInt(m[1], 10);
        const nm = a.textContent.trim();
        if (!nm || /my\s*team/i.test(nm)) return;
        const cur = teams.find((x) => x.teamId === tid);
        if (!cur) { seen[tid] = 1; teams.push({ teamId: tid, name: nm }); }
        else if (nm.length > cur.name.length) cur.name = nm;
      });
      if (!teams.length) throw new Error('no team links on league home');
      const out = [];
      for (let i = 0; i < teams.length; i++) {
        const t = teams[i];
        state.seasonStatus = 'Reading rosters… ' + (i + 1) + '/' + teams.length;
        render();
        try {
          const doc = await fetchDoc('/f1/' + lid + '/' + t.teamId);
          out.push({ teamId: t.teamId, name: t.name, entries: parseRosterDoc(doc) });
        } catch (e) { out.push({ teamId: t.teamId, name: t.name, entries: [] }); }
        await new Promise((r) => setTimeout(r, 250));
      }
      state.seasonTeams = out;
      store.set({ [cacheKey]: { day, myTeamId: state.myTeamId, teams: out.map((t) => ({
        teamId: t.teamId, name: t.name,
        entries: t.entries.map((e) => ({ name: e.name, pos: e.pos, team: e.team,
          slotLbl: e.slotLbl, inj: e.inj || null })),
      })) } });
      state.seasonStatus = state.players.length + ' players · rosters read';
      if (state.seasonTab === 'sims') setTimeout(ensureSeasonSim, 0);
    } catch (e) {
      state.seasonStatus = 'Roster read failed: ' + (e.message || e);
    }
    _rostersLoading = false;
    render();
  }
  async function ensureSeasonSim() {
    const lid = state.leagueId;
    const ps = state.seasonSim;
    if (!lid || !simAvailable()) return;
    if (!state.seasonTeams.length) { fetchLeagueRosters(); return; }
    const recHash = simRecHash();
    if (ps.leagueId === lid &&
      (ps.status === 'running' || (ps.status === 'done' && ps.recHash === recHash))) return;
    ps.leagueId = lid; ps.status = 'running'; ps.note = '';
    render();
    await new Promise((r) => setTimeout(r, 30)); // let the status paint before the sync sim
    try {
      const day = new Date().toDateString();
      const cacheKey = 'yahooSim_' + lid;
      try { // day+roster-keyed cache: finish distributions barely move intraday
        const saved = await store.get([cacheKey]);
        const c = saved[cacheKey];
        if (c && c.v === 1 && c.day === day && c.recHash === recHash && c.results) {
          Object.assign(ps, { status: 'done', results: c.results, placeCounts: c.placeCounts,
            sims: c.sims || SIM_RUNS, recHash, synthPairs: true });
          render();
          return;
        }
      } catch (e) {}
      const E2 = window.SimEngine;
      const sched = E2.buildSchedule();
      if (!sched || !Object.keys(sched.byTeam).length) throw new Error('no Vegas lines loaded');
      const curWeek = state.byesActive ? state.seasonWeek : 1;
      const playoffStart = state.playoffStart || 15;
      const regWeeks = [];
      for (let w = curWeek; w < playoffStart; w++) regWeeks.push(w);
      const teams = simTeams();
      const pairsByWeek = simRoundRobin(teams.map((t) => t.rosterId), regWeeks);
      simEnsureGlobals();
      const players = E2.buildPlayers(sched);
      const res = E2.simLeague({
        teams, sims: SIM_RUNS, seed: SIM_SEED,
        scoring: E2.scoringFromLeague(state.leagueScoring),
        schedule: sched, players, pairsByWeek, regWeeks,
        playoffTeams: state.playoffTeams || 6, playoffStart,
        lineupSlots: state.seasonSlots || [], unavailable: simUnavailable(), currentWeek: curWeek,
      });
      const placeCounts = {}, results = {};
      res.forEach((r) => {
        placeCounts[r.team.rosterId] = r.placeCounts;
        const games = regWeeks.length;
        const weekly = {};
        Object.keys(r.weekly || {}).forEach((wk) => {
          const w = r.weekly[wk];
          weekly[wk] = { opp: w.opp, winPct: +w.winPct.toFixed(3), pf: +w.avgPf.toFixed(1), pa: +w.avgPa.toFixed(1) };
        });
        results[r.team.rosterId] = {
          w: +r.avgWins.toFixed(1), l: +(games - r.avgWins).toFixed(1), pf: Math.round(r.avgPF),
          playoff: +r.playoffOdds.toFixed(3), bye: +r.byeOdds.toFixed(3),
          finals: +r.finalsOdds.toFixed(3), title: +r.titleOdds.toFixed(3), weekly,
        };
      });
      Object.assign(ps, { status: 'done', placeCounts, results, sims: SIM_RUNS, recHash });
      store.set({ [cacheKey]: { v: 1, day, recHash, placeCounts, results, sims: SIM_RUNS } });
    } catch (e) {
      ps.status = 'error';
      ps.note = e.message || String(e);
    }
    render();
  }
  function simExpFinish(rid) {
    const ps = state.seasonSim;
    const f = ps.status === 'done' && ps.placeCounts ? ps.placeCounts[rid] : null;
    if (!f) return null;
    const n = state.seasonTeams.length || 12;
    let ev = 0, mode = 1, modeP = 0;
    for (let pl = 1; pl <= n; pl++) {
      const p = (f[pl] || 0) / ps.sims;
      ev += pl * p;
      if (p > modeP) { modeP = p; mode = pl; }
    }
    return { ev, mode, modeP };
  }
  function simOrdinal(v) {
    const s = ['th', 'st', 'nd', 'rd'], t = v % 100;
    return v + (s[(t - 20) % 10] || s[t] || s[0]);
  }
  function seasonSimsHTML() {
    const ps = state.seasonSim;
    if (ps.status === 'running' || _rostersLoading) {
      return seasonHeaderHTML() +
        `<div style="padding:16px 6px;color:#8a8d96;font-size:12px">${_rostersLoading ? esc(state.seasonStatus) : 'Running ' + SIM_RUNS.toLocaleString() + ' season sims…'}</div>`;
    }
    if (ps.status === 'idle') setTimeout(ensureSeasonSim, 0);
    const note = ps.status === 'error'
      ? `<div style="background:#402a2a;color:#d06d6d;font-size:10px;padding:4px 6px;border-radius:4px;margin-bottom:6px">Sim unavailable: ${esc(ps.note || 'unknown')}</div>` : '';
    const myRid = state.myTeamId;
    const nameById = {};
    state.seasonTeams.forEach((t) => { nameById[t.teamId] = t.name; });
    const R = ps.results || {};
    const selRid = ps.selTeam != null ? ps.selTeam : myRid;
    const standOrder = state.seasonTeams.map((t) => t.teamId)
      .sort((a, b) => {
        const ra = R[a], rb = R[b];
        if (!ra || !rb) return 0;
        return (rb.w - ra.w) || (rb.pf - ra.pf);
      });
    const pct1 = (v) => v == null ? '—' : Math.round(v * 100) + '%';
    const standRows = Object.keys(R).length ? standOrder.map((rid) => {
      const r = R[rid];
      if (!r) return '';
      const fin = simExpFinish(rid);
      const sel = rid === selRid;
      return `<tr data-simteam="${rid}" style="cursor:pointer;${rid === myRid ? 'color:#b9e28c;' : ''}${sel ? 'background:#1c1e24;' : ''}border-bottom:1px solid #232529">
          <td style="padding:2px 4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:95px">${sel ? '▸ ' : ''}${esc(nameById[rid] || rid)}</td>
          <td style="text-align:center;padding:2px 3px;white-space:nowrap">${r.w}-${r.l}</td>
          <td style="text-align:right;padding:2px 3px">${r.pf.toLocaleString()}</td>
          <td style="text-align:right;padding:2px 3px">${pct1(r.playoff)}</td>
          <td style="text-align:right;padding:2px 3px">${pct1(r.title)}</td>
          <td style="text-align:center;color:#8a8d96;padding:2px 3px;white-space:nowrap">${fin ? simOrdinal(fin.mode) : '—'}</td>
        </tr>`;
    }).join('') : '';
    const sel = R[selRid];
    let weeklyHtml = '';
    if (sel) {
      const wks = Object.keys(sel.weekly || {}).map(Number).sort((a, b) => a - b);
      const wkRows = wks.map((wk) => {
        const w = sel.weekly[wk];
        const wp = Math.round(w.winPct * 100);
        const col = wp >= 60 ? '#22c55e' : wp <= 40 ? '#d06d6d' : '#ffc166';
        return `<tr style="border-bottom:1px solid #232529">
            <td style="padding:2px 4px;color:#8a8d96">W${wk}</td>
            <td style="padding:2px 4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:105px">${esc(nameById[w.opp] || w.opp)}</td>
            <td style="text-align:right;padding:2px 4px;color:${col};font-weight:600">${wp}%</td>
            <td style="text-align:right;padding:2px 4px">${w.pf.toFixed(1)}</td>
            <td style="text-align:right;padding:2px 4px;color:#8a8d96">${w.pa.toFixed(1)}</td>
          </tr>`;
      }).join('');
      weeklyHtml = `
        <div style="font-size:10px;color:#8a8d96;text-transform:uppercase;letter-spacing:.5px;margin:10px 0 3px">Week by week · ${esc(nameById[selRid] || selRid)}</div>
        <div style="font-size:10px;color:#8a8d96;margin-bottom:3px">Playoffs ${pct1(sel.playoff)}${sel.bye ? ' · Bye ' + pct1(sel.bye) : ''} · Finals ${pct1(sel.finals)} · Title ${pct1(sel.title)}</div>
        ${wkRows ? `<table style="width:100%;border-collapse:collapse;font-size:11px">
          <thead><tr style="color:#8a8d96;font-size:9px;text-transform:uppercase">
            <th style="text-align:left;padding:2px 4px">Wk</th><th style="text-align:left;padding:2px 4px">Opp</th>
            <th style="text-align:right;padding:2px 4px">Win</th><th style="text-align:right;padding:2px 4px">Proj</th>
            <th style="text-align:right;padding:2px 4px">Opp proj</th>
          </tr></thead><tbody>${wkRows}</tbody></table>` : '<div style="font-size:11px;color:#8a8d96;padding:2px">No remaining regular-season weeks.</div>'}`;
    }
    const standingsHtml = standRows ? `
      <div style="font-size:10px;color:#8a8d96;text-transform:uppercase;letter-spacing:.5px;margin:2px 0 3px">Projected standings <span style="text-transform:none">(tap a team)</span></div>
      <table style="width:100%;border-collapse:collapse;font-size:11px">
        <thead><tr style="color:#8a8d96;font-size:9px;text-transform:uppercase">
          <th style="text-align:left;padding:2px 4px">Team</th><th style="padding:2px 3px">Rec</th>
          <th style="text-align:right;padding:2px 3px">PF</th><th style="text-align:right;padding:2px 3px">PO</th>
          <th style="text-align:right;padding:2px 3px">Title</th><th style="padding:2px 3px">Fin</th>
        </tr></thead><tbody>${standRows}</tbody></table>${weeklyHtml}` : '';
    const statTxt = ps.status === 'done' ? SIM_RUNS.toLocaleString() + ' sims · synth schedule' : '';
    return `${seasonHeaderHTML()}${note}${standingsHtml}
      <div style="display:flex;align-items:center;gap:6px;margin-top:8px">
        <button id="mff-sim-rerun" style="background:#2a2c33;border:none;color:#e9e9ec;padding:3px 8px;border-radius:4px;cursor:pointer;font-size:10px;font-weight:600">RE-RUN SIM</button>
        <span style="font-size:9px;color:#8a8d96">${statTxt}</span>
      </div>
      <div style="font-size:9px;color:#8a8d96;margin-top:6px;line-height:1.35">Standings/odds = ${SIM_RUNS.toLocaleString()} Monte Carlo seasons (Clay projections × Vegas lines, scored to this league's settings). Yahoo doesn't expose real matchup pairings, so a synthetic round-robin schedule is used. Rosters read from each team page, refreshed daily; IR-slot players excluded; players without a Clay projection score 0.</div>`;
  }

  // ---------- UI ----------
  let root = null;
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }
  function buildPanel() {
    if (root) return;
    root = document.createElement('div');
    root.id = 'mff-sidebar';
    root.innerHTML = `
      <div id="mff-header">
        <span class="title">MFF YAHOO HELPER</span>
        <div class="controls">
          <button id="mff-collapse" title="Collapse">–</button>
          <button id="mff-close" title="Hide (reopen from the MFF chip)">✕</button>
        </div>
      </div>
      <div id="mff-body"></div>
      <div id="mff-resize-n" class="mff-resize-edge"></div>
      <div id="mff-resize-e" class="mff-resize-edge"></div>
      <div id="mff-resize-s" class="mff-resize-edge"></div>
      <div id="mff-resize"></div>`;
    document.body.appendChild(root);
    root.querySelector('#mff-collapse').addEventListener('click', () => {
      root.classList.toggle('collapsed');
    });
    root.querySelector('#mff-close').addEventListener('click', hidePanel);
    enableDrag();
    enableResize();
    root.querySelector('#mff-body').addEventListener('click', onBodyClick);
    root.querySelector('#mff-body').addEventListener('change', onBodyChange);
  }
  function destroyPanel() {
    if (root) { root.remove(); root = null; }
    const chip = document.getElementById('mff-reopen');
    if (chip) chip.remove();
    if (state.pollTimer) { clearInterval(state.pollTimer); state.pollTimer = null; }
    if (state.scrapeTimer) { clearInterval(state.scrapeTimer); state.scrapeTimer = null; }
  }
  function hidePanel() {
    if (!root) return;
    root.style.display = 'none';
    if (document.getElementById('mff-reopen')) return;
    const chip = document.createElement('div');
    chip.id = 'mff-reopen';
    chip.textContent = 'MFF';
    chip.title = 'Show MFF Yahoo Helper';
    chip.style.cssText = 'position:fixed;bottom:18px;right:18px;z-index:2147483647;' +
      'background:#7d2eff;color:#ffffff;font:700 11px -apple-system,BlinkMacSystemFont,sans-serif;' +
      'padding:8px 11px;border-radius:20px;cursor:pointer;box-shadow:0 4px 14px rgba(0,0,0,0.5);user-select:none';
    chip.addEventListener('click', () => {
      chip.remove();
      if (root) root.style.display = 'flex';
    });
    document.body.appendChild(chip);
  }
  function enableDrag() {
    const header = root.querySelector('#mff-header');
    let sx, sy, ox, oy, dragging = false;
    header.addEventListener('mousedown', (e) => {
      if (e.target.closest('button')) return;
      dragging = true;
      sx = e.clientX; sy = e.clientY;
      const r = root.getBoundingClientRect();
      ox = r.left; oy = r.top;
      e.preventDefault();
    });
    window.addEventListener('mousemove', (e) => {
      if (!dragging) return;
      root.style.left = ox + (e.clientX - sx) + 'px';
      root.style.top = Math.max(0, oy + (e.clientY - sy)) + 'px';
      root.style.right = 'auto';
    });
    window.addEventListener('mouseup', () => { dragging = false; });
  }
  function enableResize() {
    let sx, sy, sw, sh, st, mode = null;
    function arm(id, m) {
      const h = root.querySelector(id);
      if (!h) return;
      h.addEventListener('mousedown', (e) => {
        mode = m;
        sx = e.clientX; sy = e.clientY;
        const r = root.getBoundingClientRect();
        sw = r.width; sh = r.height; st = r.top;
        e.preventDefault();
      });
    }
    arm('#mff-resize', 'se');
    arm('#mff-resize-e', 'e');
    arm('#mff-resize-s', 's');
    arm('#mff-resize-n', 'n');
    window.addEventListener('mousemove', (e) => {
      if (!mode) return;
      root.style.maxHeight = 'none';
      const dx = e.clientX - sx, dy = e.clientY - sy;
      if (mode === 'se' || mode === 'e') root.style.width = Math.max(300, sw + dx) + 'px';
      if (mode === 'se' || mode === 's') root.style.height = Math.max(200, sh + dy) + 'px';
      if (mode === 'n') {
        const newTop = Math.max(0, st + dy);
        root.style.top = newTop + 'px';
        root.style.height = Math.max(200, sh + (st - newTop)) + 'px';
      }
    });
    window.addEventListener('mouseup', () => { mode = null; });
  }
  function render() {
    if (!root) return;
    if (!isDynMode() && state.seasonTeamSrc === 'ktc') state.seasonTeamSrc = 'jack';
    const body = root.querySelector('#mff-body');
    if (!body) return;
    if (!gateAllowed()) { body.innerHTML = gateLockHTML(); return; }
    const recsEl = body.querySelector('#mff-recs');
    const scrollTop = recsEl ? recsEl.scrollTop : 0;
    body.innerHTML = seasonHTML();
    const newRecs = body.querySelector('#mff-recs');
    if (newRecs) newRecs.scrollTop = scrollTop;
  }

  function snBadges(p) {
    let out = '';
    if (onByeThisWeek(p)) {
      out += '<span class="tag" style="background:#3a3040;color:#c0a0d0">BYE</span>';
    }
    const inj = injOf(p);
    if (inj) {
      const cfg = inj === 'OUT' ? ['#402a2a', '#d06d6d', 'OUT']
        : inj === 'D' ? ['#453325', '#e0a060', 'DTD']
        : ['#4a3f30', '#ffc99b', 'Q'];
      out += `<span class="tag" style="background:${cfg[0]};color:${cfg[1]}">${cfg[2]}</span>`;
    }
    return out;
  }
  function seasonHeaderHTML() {
    const modeLbl = MODES[state.mode] ? MODES[state.mode].label : '';
    const hasProps = !!(state.wkPropsAll && state.wkPropsAll[String(state.seasonWeek)]);
    return `
      <div id="mff-pick-line">
        <span class="pl-pick">${esc(state.teamName || ('League ' + (state.leagueId || '')))}</span>
        <span class="pl-sep">·</span><span class="pl-round">Wk ${state.seasonWeek}${state.byesActive ? '' : ' (pre)'}</span>
        <span class="pl-sep">·</span><span class="pl-mine">${esc(state.scoringLabel)}</span>
        <span class="pl-sep">·</span><span class="pl-mine">${esc(modeLbl)}</span>
        ${hasProps ? '<span class="pl-sep">·</span><span class="pl-mine" style="color:#6dd06d" title="Weekly values blend the site\'s Wk ' + state.seasonWeek + ' prop boards (UD+PP) with Clay projections + Jack\'s rank">W' + state.seasonWeek + ' props</span>' : ''}
      </div>`;
  }
  function profileHTML(p, k) {
    const mk = modeKeys();
    const modeLbl = MODES[state.mode].label;
    const sfMode = state.mode.endsWith('_sf');
    const rows = [
      ["Jack " + modeLbl, p[mk.jack] == null ? null
        : '#' + p[mk.jack] + (() => { const t = jackTierFor(p[mk.jack]); return t ? ' · ' + (t.n || 'Tier ' + t.l) : ''; })()],
      ["Jack Redraft", mk.jack !== 'rank' && p.rank != null ? '#' + p.rank : null],
      ['FP ' + modeLbl, p[mk.fp] == null ? null : '#' + p[mk.fp]],
      ['Sleeper ' + modeLbl, p[mk.sl] == null ? null : '#' + p[mk.sl]],
      ['ADP ' + modeLbl, p[mk.adp]],
      ['KTC Superflex', isDynMode() ? p.ktcSf : null],
      ['KTC 1QB', isDynMode() ? p.ktc1qb : null],
      ['Proj PPG (Clay, ' + state.scoringLabel + ')', p.pPg],
      ['Proj Season', p.szn],
      ['Ceiling PPG', p.cPpg],
      ['VOR' + (sfMode ? ' (SF)' : ''), p[mk.vor]],
      ['Upside' + (sfMode ? ' (SF)' : ''), p[mk.up]],
      ['Age', p.age], ["'25 PPG", p.p25],
      ['Team', p.sTm || p.t],
    ].filter((r) => r[1] != null)
      .map((r) => `<div class="prof-row"><span class="k">${r[0]}</span><span class="v">${esc(r[1])}</span></div>`)
      .join('');
    let sosRow = '';
    const sosData = window.MFF_PLAYOFF_SOS;
    const sos = sosData && p.sTm && sosData[p.sTm] && sosData[p.sTm][p.s];
    if (sos) {
      const pills = ['15', '16', '17'].map((w) => {
        const m = sos[w];
        if (!m) return '';
        return `<span style="background:${esc(m.color)};color:#0e0f12;border-radius:3px;padding:1px 5px;font-size:9px;font-weight:700" title="SOS rank ${m.rank}/32 · implied ${m.impliedTotal} pts">W${w} ${m.home ? 'vs' : '@'}${esc(m.opp)}</span>`;
      }).join('');
      sosRow = `<div class="prof-row"><span class="k">Playoff SOS</span><span class="v" style="display:flex;gap:3px;flex-wrap:wrap">${pills}</span></div>`;
    }
    return `<div class="mff-profile" style="pointer-events:auto">${rows}${sosRow}</div>`;
  }
  function seasonLineupHTML() {
    if (!state.roster.length || !state.seasonSlots) {
      return seasonHeaderHTML() +
        '<div class="mff-proj-empty">Open YOUR team page (My Team) so the helper can read your roster.</div>';
    }
    const calc = seasonLineupCalc();
    const pool = calc.pool;
    const opt = calc.opt;
    const starterSet = calc.starterSet;
    const moves = calc.moves;
    const optKeys = new Set(opt.assign.filter((a) => a.e).map((a) => keyOf(a.e.p)));
    const rowCls = {};
    for (const k of Object.keys(calc.cls)) rowCls[k] = 'mff-row-' + calc.cls[k];
    const POS_COLORS = { QB: '#c084fc', RB: '#4ade80', WR: '#fb923c', TE: '#60a5fa', K: '#bd66ff', DEF: '#7988a1' };
    const rows = opt.assign.map((a) => {
      const slotLbl = a.slot === 'SUPER_FLEX' ? 'SFLX' : a.slot === 'WRRB_FLEX' ? 'W/R'
        : a.slot === 'REC_FLEX' ? 'W/T' : a.slot === 'FLEX' ? 'W/R/T' : a.slot === 'DEF' ? 'DEF' : a.slot;
      const col = POS_COLORS[a.slot] || '#8a8d96';
      if (!a.e) {
        return `<div class="mff-proj-roster-player"><span class="t" style="color:${col}">${esc(slotLbl)}</span>
          <span class="n" style="color:#d06d6d">— empty${SLOT_ELIG[a.slot] ? '' : ' (unsupported slot)'}</span><span class="v"></span></div>`;
      }
      const p = a.e.p;
      const k = keyOf(p);
      const cls = rowCls[k] || '';
      const starting = starterSet.has(k);
      const mark = starting ? '<span style="color:#5a5d66">✓</span>'
        : cls === 'mff-row-close'
          ? '<span style="color:#ffc166;font-weight:800" title="Toss-up — projections are very close">≈</span>'
          : '<span style="color:#6dd06d;font-weight:800" title="Currently on your bench — start him">▲</span>';
      return `<div class="mff-proj-roster-player mff-rec ${cls}" data-key="${esc(k)}" style="cursor:pointer">
        <span class="t" style="color:${col}">${esc(slotLbl)}</span>
        <span class="n">${mark} ${esc(p.n)} ${wkOppHTML(p)}${snBadges(p)}${p._unmatched ? ' <span style="color:#8a8d96;font-size:9px">(no proj)</span>' : ''}</span>
        <span class="v" title="Projected ppg this week (${esc(state.scoringLabel)})">${a.e.v ? a.e.v.toFixed(1) : '0'}</span>
        ${state.expandedKey === k && !p._unmatched ? profileHTML(p, k) : ''}
      </div>`;
    }).join('');
    let movesHtml = '';
    if (moves.length) {
      movesHtml = '<div class="mff-section"><h3>Start / Sit moves</h3>' + moves.map((mv) => {
        const isClose = mv.sit && mv.delta != null && Math.abs(mv.delta) < CLOSE_PPG;
        if (isClose) {
          return `<div style="font-size:11px;color:#ffc166;padding:2px 2px">≈ Toss-up: <b>${esc(mv.add.p.n)}</b> / <b>${esc(mv.sit.p.n)}</b> <span style="color:#8a8d96">(${mv.delta >= 0 ? '+' : ''}${mv.delta.toFixed(1)})</span></div>`;
        }
        const sitTxt = mv.sit ? ' over <b style="color:#d06d6d">' + esc(mv.sit.p.n) + '</b>' : '';
        const d = mv.delta != null && mv.delta > 0 ? ` <span class="tag STEAL">+${mv.delta.toFixed(1)}</span>` : '';
        return `<div style="font-size:11px;color:#c8ccd4;padding:2px 2px">▲ Start <b style="color:#6dd06d">${esc(mv.add.p.n)}</b>${sitTxt}${d}</div>`;
      }).join('') + '</div>';
    } else if (starterSet.size) {
      movesHtml = '<div class="mff-section"><h3>Start / Sit moves</h3>' +
        '<div style="font-size:11px;color:#6dd06d;padding:2px">✓ Your lineup is already optimal</div></div>';
    }
    const bench = pool.filter((p) => !optKeys.has(keyOf(p)))
      .map((p) => ({ p, v: wkVal(p) })).sort((a, b) => b.v - a.v);
    const benchRows = bench.map((b) => {
      const k = keyOf(b.p);
      const cls = rowCls[k] || '';
      const mark = cls === 'mff-row-sit'
        ? '<span style="color:#d06d6d;font-weight:800" title="Currently starting — bench him">▼</span> '
        : cls === 'mff-row-close'
          ? '<span style="color:#ffc166;font-weight:800" title="Toss-up — projections are very close">≈</span> '
          : '';
      return `
      <div class="mff-proj-roster-player mff-rec ${cls}" data-key="${esc(k)}" style="cursor:pointer">
        <span class="t">${esc(b.p.s)}</span>
        <span class="n">${mark}${esc(b.p.n)} ${wkOppHTML(b.p)}${snBadges(b.p)}</span>
        <span class="v" title="Projected ppg this week (${esc(state.scoringLabel)})">${b.v ? b.v.toFixed(1) : '0'}</span>
        ${state.expandedKey === k && !b.p._unmatched ? profileHTML(b.p, k) : ''}
      </div>`;
    }).join('');
    const stale = state.rosterTs && Date.now() - state.rosterTs > 24 * 3600 * 1000;
    return `
      ${seasonHeaderHTML()}
      ${stale ? '<div style="font-size:10px;color:#ffc99b;padding:2px">Roster last read ' + Math.round((Date.now() - state.rosterTs) / 3600000) + 'h ago — open your team page to refresh.</div>' : ''}
      ${movesHtml}
      <div class="mff-section"><h3>Optimal lineup <span style="color:#b388ff">${opt.total} ppg</span></h3>
        <div class="mff-proj-roster">${rows}</div></div>
      <div class="mff-section"><h3>Bench</h3>
        <div class="mff-proj-roster">${benchRows || '<div class="mff-proj-empty">No bench players</div>'}</div></div>`;
  }
  function seasonWaiversHTML() {
    if (!state.roster.length) {
      return seasonHeaderHTML() +
        '<div class="mff-proj-empty">Open YOUR team page first so waivers can rank vs YOUR lineup.</div>';
    }
    const posChips = ['ALL', 'QB', 'RB', 'WR', 'TE', 'K', 'DST'].map((p) =>
      `<button class="pos-filter ${state.seasonPosFilter === p ? 'active' : ''}" data-snpos="${p}">${p}</button>`
    ).join('');
    const faCount = Object.keys(state.faSeen).length;
    const drops = dropCandidates().slice(0, 3);
    const recs = waiverRecs();
    const cards = recs.map((r, i) => {
      const p = r.p;
      const k = keyOf(p);
      const expanded = state.expandedKey === 'wv|' + k;
      const upgrade = r.delta >= 0.5;
      const tags = [];
      if (upgrade) tags.push(`<span class="tag STEAL">LINEUP +${r.delta.toFixed(1)} ppg</span>`);
      else if (r.delta > 0) tags.push(`<span class="tag Value">+${r.delta.toFixed(1)} ppg</span>`);
      else tags.push('<span class="tag" style="background:#2a2c33;color:#8a8d96">DEPTH</span>');
      if (r.trend) tags.push(`<span class="tag" style="background:#453325;color:#e0a060">🔥 ${r.trend} adds</span>`);
      const dropLine = expanded && drops.length
        ? `<div class="mff-profile" style="pointer-events:auto;margin-top:2px"><div class="prof-row"><span class="k">SUGGESTED DROP</span><span class="v">${esc(drops[0].p.n)} (${esc(drops[0].p.s)})</span></div></div>`
        : '';
      return `
      <div class="mff-rec ${upgrade ? 'need' : ''}" data-key="wv|${esc(k)}">
        <div class="num">${i + 1}</div>
        <div class="info">
          <div class="name">${esc(p.n)}</div>
          <div class="meta">
            <span class="pos ${p.s}">${p.s}</span>
            <span>${esc(p.sTm || p.t || '')}</span>
            ${p.pPg != null ? `<span>${p.pPg}ppg</span>` : ''}
            ${wkOppHTML(p)}
            ${snBadges(p)}
          </div>
          <div class="why">${tags.join('')}</div>
        </div>
        <div class="score" style="color:${upgrade ? '#6dd06d' : '#8a8d96'}">${r.delta > 0 ? '+' + r.delta.toFixed(1) : '·'}</div>
        ${expanded ? profileHTML(p, k) + dropLine : ''}
      </div>`;
    }).join('');
    const dropWatch = drops.length
      ? `<div class="mff-section"><h3>Drop watch</h3>${drops.map((d) =>
          `<div style="font-size:11px;color:#c8ccd4;padding:1px 2px">${esc(d.p.n)} <span style="color:#8a8d96">(${esc(d.p.s)} · ${d.marginal > 0 ? 'costs ' + d.marginal.toFixed(1) + ' ppg' : 'not in lineup'})</span></div>`
        ).join('')}</div>`
      : '';
    return `
      ${seasonHeaderHTML()}
      <div class="mff-section"><h3>Waiver targets <span style="color:#8a8d96;font-weight:400;font-size:9px">vs your lineup</span></h3>
        <div style="font-size:10px;color:#8a8d96;margin-bottom:3px">${faCount} free agents captured — browse your league's <b>Players</b> page (Available filter) to add more; rows you see are captured automatically.</div>
        <div id="mff-pos-toggle" style="display:flex;gap:3px;margin-bottom:4px">${posChips}</div>
        <div id="mff-recs">${cards || '<div class="mff-proj-empty">No free agents captured yet — open the league Players page.</div>'}</div>
      </div>
      ${dropWatch}`;
  }
  const POS_ORDER = ['QB', 'RB', 'WR', 'TE', 'K', 'DST'];
  function seasonTeamHTML() {
    if (!state.roster.length) {
      return seasonHeaderHTML() +
        '<div style="font-size:11px;color:#8a8d96;padding:8px 2px">Open YOUR team page first.</div>';
    }
    const srcId = (SOURCES[state.seasonTeamSrc] && (state.seasonTeamSrc !== 'ktc' || isDynMode()))
      ? state.seasonTeamSrc : (isDynMode() ? 'ktc' : 'jack');
    const src = SOURCES[srcId];
    const chips = Object.entries(SOURCES)
      .filter(([id]) => id !== 'ktc' || isDynMode()) // KTC = dynasty-only
      .filter(([id]) => id !== 'mine' || myRanksAvailable())
      .map(([id, s]) =>
      `<button class="pos-filter ${id === srcId ? 'active' : ''}" data-pksrc="${id}" style="flex:0 0 auto">${
        id === 'ktc' ? 'KTC' : id === 'jack' ? "JACK'S" : id === 'fp' ? 'FP' : id === 'mine' ? 'MINE' : 'SLPR'}</button>`).join('');
    const mine = myPlayerObjs();
    const val = (p) => p._unmatched ? null : src.get(p);
    const groups = POS_ORDER.map((pos) => {
      const list = mine.filter((p) => p.s === pos).sort((a, b) => {
        const va = val(a), vb = val(b);
        if (va == null && vb == null) return 0;
        if (va == null) return 1;
        if (vb == null) return -1;
        return src.desc ? vb - va : va - vb;
      });
      if (!list.length) return '';
      const sub = srcId === 'ktc'
        ? list.reduce((t, p) => t + (val(p) || 0), 0) : null;
      const rows = list.map((p) => {
        const v = val(p);
        const inj = injOf(p);
        const t = srcId === 'jack' ? jackTierFor(p[modeKeys().jack]) : null;
        const tierB = t ? ` <b class="mff-jtier" style="color:${jackTierColor(t.l)}" title="Jack's tier: ${esc(t.n || t.l)}">${esc(t.l)}</b>` : '';
        return `<div style="display:flex;justify-content:space-between;align-items:baseline;padding:2px 2px;border-bottom:1px solid #232529;font-size:12px">
            <span style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:200px">${esc(p.n)}
              <span style="color:#8a8d96;font-size:10px">${esc(p.sTm || '')}${p.age ? ' · ' + p.age : ''}${inj ? ' · <span style="color:#d06d6d">' + inj + '</span>' : ''}</span></span>
            <span style="font-weight:600;color:${v == null ? '#8a8d96' : '#e9e9ec'}">${
              v == null ? '—' : src.desc ? v.toLocaleString() : '#' + v}${tierB}</span>
          </div>`;
      }).join('');
      return `<div style="display:flex;justify-content:space-between;font-size:10px;color:#8a8d96;text-transform:uppercase;letter-spacing:.5px;margin:8px 0 2px">
          <span class="pos pos-${pos.toLowerCase()}" style="padding:0 5px;border-radius:3px">${pos}</span>
          ${sub != null ? '<span>' + sub.toLocaleString() + '</span>' : ''}</div>${rows}`;
    }).join('');
    const total = srcId === 'ktc' ? mine.reduce((t, p) => t + (val(p) || 0), 0) : null;
    return `
      ${seasonHeaderHTML()}
      <div style="display:flex;gap:3px;flex-wrap:wrap;margin-bottom:4px">${chips}</div>
      ${total != null ? `<div style="display:flex;justify-content:space-between;font-size:12px;padding:2px;border-bottom:1px solid #2a2c33"><b>Team total (${esc(src.label)} ${state.mode.endsWith('_sf') ? 'SF' : '1QB'})</b><b style="color:#b388ff">${total.toLocaleString()}</b></div>` : ''}
      ${groups}
      <div style="font-size:9px;color:#8a8d96;margin-top:6px">${esc(src.label)} in the selected format (${state.mode.replace('_', ' ').toUpperCase()}). Players outside the export show —.</div>`;
  }
  function seasonSettingsHTML() {
    let ver = '';
    try { ver = chrome.runtime.getManifest().version; } catch (e) {}
    const recChips = [[1, 'PPR'], [0.5, '½PPR'], [0, 'STD']].map(([v, lbl]) =>
      `<button class="pos-filter ${state.scoringPrefs.rec === v ? 'active' : ''}" data-snrec="${v}" style="flex:0 0 auto">${lbl}</button>`).join('');
    const tdChips = [[4, '4pt paTD'], [6, '6pt paTD']].map(([v, lbl]) =>
      `<button class="pos-filter ${state.scoringPrefs.passTd === v ? 'active' : ''}" data-snptd="${v}" style="flex:0 0 auto">${lbl}</button>`).join('');
    const modeOpts = Object.entries(MODES).map(([k, m]) =>
      `<option value="${k}" ${state.mode === k ? 'selected' : ''}>${m.label}${state.modeDetected === k ? ' ✓' : ''}</option>`).join('');
    return `
      ${seasonHeaderHTML()}
      <div class="mff-section"><h3>Scoring <span style="color:#8a8d96;font-weight:400;font-size:9px">${state.scoringManual ? '(manual override)' : state.apiScoring ? '(✓ read from your league settings)' : '(league settings unavailable — set yours)'}</span></h3>
        <div style="display:flex;gap:3px;margin-bottom:3px">${recChips}</div>
        <div style="display:flex;gap:3px">${tdChips}</div></div>
      <div class="mff-section"><h3>Format</h3>
        <select class="mff-select" id="mff-mode">${modeOpts}</select>
        <div style="font-size:9px;color:#8a8d96;margin-top:2px">SF auto-detects from your lineup slots; dynasty can't be scraped — pick it here.</div></div>
      <div class="mff-section"><h3>Roster</h3>
        <div style="font-size:11px;color:#c8ccd4">${state.roster.length ? state.roster.length + ' players · read ' + (state.rosterTs ? Math.round((Date.now() - state.rosterTs) / 60000) + ' min ago' : '—') : 'not read yet — open your team page'}</div>
        <div style="font-size:11px;color:#c8ccd4">${Object.keys(state.faSeen).length} free agents captured from the Players page</div>
        <button data-clearfa="1" class="pos-filter" style="margin-top:3px">CLEAR FA CACHE</button></div>
      <div class="mff-section"><h3>API probe</h3>
        <div style="font-size:10px;color:#8a8d96">${state.probeCount} internal endpoints recorded this session (upgrade path off DOM scraping).</div>
        <button data-copyprobe="1" class="pos-filter" style="margin-top:3px">COPY PROBE LOG</button></div>
      <div style="font-size:10px;color:#8a8d96">Players: ${state.players.length} · data ${esc(state.exportedAt)}${ver ? ' · v' + ver : ''}</div>`;
  }
  function seasonHTML() {
    const tabs = [['lineup', 'LINEUP'], ['team', 'TEAM'], ['waivers', 'WAIVERS']]
      .concat(simAvailable() ? [['sims', 'SIMS']] : [])
      .concat([['snset', 'SETTINGS']])
      .map(([id, lbl]) =>
        `<button class="mff-tab ${state.seasonTab === id ? 'active' : ''}" data-sntab="${id}">${lbl}</button>`).join('');
    const content = state.seasonTab === 'waivers' ? seasonWaiversHTML()
      : state.seasonTab === 'team' ? seasonTeamHTML()
      : state.seasonTab === 'sims' && simAvailable() ? seasonSimsHTML()
      : state.seasonTab === 'snset' ? seasonSettingsHTML()
      : seasonLineupHTML();
    return `
      <div id="mff-tabs">${tabs}</div>
      ${content}
      <div id="mff-mode-line" style="display:flex;gap:6px;font-size:10px;color:#8a8d96;align-items:center">
        <span class="badge live" style="background:#2a4030;color:#6dd06d;padding:2px 6px;border-radius:3px;letter-spacing:0.5px;text-transform:uppercase;font-weight:600">SEASON</span>
        <span id="mff-status-line" style="flex:1">${esc(state.seasonStatus)}</span>
      </div>`;
  }

  // ---------- events ----------
  function onBodyClick(e) {
    const snTab = e.target.closest('[data-sntab]');
    if (snTab) {
      state.seasonTab = snTab.dataset.sntab;
      saveLeagueState();
      render();
      if (state.seasonTab === 'sims' && simAvailable()) setTimeout(ensureSeasonSim, 0);
      return;
    }
    const simTeam = e.target.closest('[data-simteam]');
    if (simTeam) {
      state.seasonSim.selTeam = parseInt(simTeam.dataset.simteam, 10);
      render();
      return;
    }
    if (e.target.closest('#mff-sim-rerun')) {
      const lid = state.leagueId;
      store.set({ ['yahooSim_' + lid]: null, ['yahooRosters_' + lid]: null });
      state.seasonSim.status = 'idle';
      state.seasonSim.recHash = null;
      state.seasonTeams = [];
      fetchLeagueRosters(true);
      return;
    }
    const snPos = e.target.closest('[data-snpos]');
    if (snPos) {
      state.seasonPosFilter = snPos.dataset.snpos;
      saveLeagueState();
      render();
      return;
    }
    const pkSrc = e.target.closest('[data-pksrc]');
    if (pkSrc) {
      state.seasonTeamSrc = pkSrc.dataset.pksrc;
      saveLeagueState();
      render();
      return;
    }
    const rec = e.target.closest('[data-snrec]');
    if (rec) {
      state.scoringPrefs.rec = parseFloat(rec.dataset.snrec);
      state.scoringManual = true;
      applyScoringPrefs();
      saveLeagueState();
      render();
      return;
    }
    const ptd = e.target.closest('[data-snptd]');
    if (ptd) {
      state.scoringPrefs.passTd = parseInt(ptd.dataset.snptd, 10);
      state.scoringManual = true;
      applyScoringPrefs();
      saveLeagueState();
      render();
      return;
    }
    if (e.target.closest('[data-clearfa]')) {
      state.faSeen = {};
      saveLeagueState();
      render();
      return;
    }
    if (e.target.closest('[data-copyprobe]')) {
      store.get(['mff_yahoo_probe']).then((saved) => {
        const log = saved.mff_yahoo_probe || { urls: [] };
        try {
          navigator.clipboard.writeText(JSON.stringify(log, null, 2));
          state.seasonStatus = 'Probe log copied (' + (log.urls || []).length + ' endpoints)';
        } catch (err) {
          console.log('[MFF/yahoo] probe log:', log);
          state.seasonStatus = 'Clipboard blocked — probe log dumped to console';
        }
        render();
      });
      return;
    }
    const rowEl = e.target.closest('.mff-rec[data-key]');
    if (rowEl) {
      const k = rowEl.dataset.key;
      state.expandedKey = state.expandedKey === k ? null : k;
      render();
    }
  }
  function onBodyChange(e) {
    if (e.target.id === 'mff-mode') {
      applyMode(e.target.value, true);
      saveLeagueState();
      render();
    }
  }

  // ---------- on-page decoration ----------
  // Yahoo's own rows get inline pills next to the player name: verdict
  // (▲ START / ▼ SIT / ≈ TOSS-UP) for YOUR roster, the colored Vegas matchup
  // pill, this week's projected ppg — and on the league Players page, the
  // "LINEUP +x.x" upgrade delta each free agent would add to your optimal
  // lineup. Runs on the same 2.5s scrape tick, signature-cached per row.
  function pillHTML(text, bg, fg, title) {
    return `<span ${title ? 'title="' + esc(title) + '"' : ''} style="background:${bg};color:${fg};` +
      'font-size:10px;font-weight:700;border-radius:3px;padding:0 4px;line-height:15px;' +
      'white-space:nowrap;flex:0 0 auto">' + esc(text) + '</span>';
  }
  function decorateYahooRows() {
    if (!gateAllowed()) return;
    if (!state.leagueId || !state.players.length) return;
    const calc = state.roster.length && state.seasonSlots ? seasonLineupCalc() : null;
    const playersPage = onPlayersPage();
    let mine = null, base = null; // lazy — only when an FA delta is needed
    document.querySelectorAll('.ysf-player-name').forEach((box) => {
      if (box.closest('#mff-sidebar')) return;
      const row = box.closest('tr') || box;
      const info = parsePlayerCell(row);
      const existing = box.querySelector(':scope > .mff-page-pills');
      if (!info || !info.p) { if (existing) existing.remove(); return; }
      const p = info.p;
      const pills = [];
      const isMine = state.myKeys.has(info.key);
      const verdict = isMine && calc ? calc.cls[keyOf(p)] : null;
      if (verdict === 'go') pills.push(pillHTML('▲ START', '#2a4030', '#6dd06d', 'Projects better than a current starter — put him in'));
      else if (verdict === 'sit') pills.push(pillHTML('▼ SIT', '#402a2a', '#d06d6d', 'A benched player projects better — take him out'));
      else if (verdict === 'close') pills.push(pillHTML('≈ TOSS-UP', '#4a3f30', '#ffc99b', 'Projections within ' + CLOSE_PPG + ' ppg — either is fine'));
      const g = wkOppInfo(p);
      if (g) pills.push(pillHTML(g.txt, g.bg, g.fg, g.tip));
      const v = wkVal(p);
      if (v > 0 || p.pPg != null) {
        pills.push(pillHTML((Math.round(v * 10) / 10) + ' proj', '#2a2c33', '#b9e28c',
          'Projected points this week (' + state.scoringLabel + ' · MFF blend of props + Clay + Jack)'));
      }
      if (playersPage && !isMine && state.faSeen[info.key] && calc) {
        if (base == null) { mine = myPlayerObjs(); base = optimalLineup(mine).total; }
        const delta = Math.round((optimalLineup(mine.concat([p])).total - base) * 10) / 10;
        if (delta >= 0.5) pills.push(pillHTML('LINEUP +' + delta.toFixed(1), '#2a4030', '#6dd06d', 'Adding him upgrades your optimal lineup by ' + delta.toFixed(1) + ' ppg'));
        else if (delta > 0) pills.push(pillHTML('+' + delta.toFixed(1), '#2a3a40', '#6dc0d0', 'Marginal lineup upgrade'));
      }
      const inner = pills.join('');
      if (existing && existing.dataset.mffSig === inner) return;
      if (existing) existing.remove();
      if (!inner) return;
      const span = document.createElement('span');
      span.className = 'mff-page-pills';
      span.dataset.mffSig = inner;
      span.innerHTML = inner;
      span.style.cssText = 'display:inline-flex;flex-wrap:nowrap;gap:3px;margin-left:6px;' +
        'vertical-align:middle;overflow:hidden;position:relative;z-index:5;';
      box.appendChild(span);
    });
  }

  // ---------- probe persistence (events from probe.js in MAIN world) ----------
  const probeUrls = [];
  document.addEventListener('mff-yahoo-probe', (e) => {
    try {
      const d = JSON.parse(e.detail);
      probeUrls.push({ t: Date.now(), kind: d.kind, url: d.url });
      state.probeCount = probeUrls.length;
      if (probeUrls.length <= 600) {
        store.set({ mff_yahoo_probe: { updatedAt: Date.now(), urls: probeUrls.slice(-600) } });
      }
    } catch (_) {}
  });

  // ---------- boot ----------
  function scrapeTick() {
    if (!state.leagueId) return;
    const scr = scrapeTeamPage();
    if (scr) {
      const sig = scr.entries.map((x) => x.key + ':' + x.slotLbl).join('|');
      if (sig !== state._rosterSig) {
        state._rosterSig = sig;
        applyScrapedRoster(scr);
        render();
      }
    }
    if (scrapePlayersPage() > 0) render();
    decorateYahooRows();
  }
  async function initForLeague(leagueId) {
    state.leagueId = leagueId;
    buildPanel();
    render();
    const saved = await store.get(['yahooLeague_' + leagueId]);
    restoreLeagueState(saved['yahooLeague_' + leagueId]);
    fetchLeagueSettings(leagueId); // async — overwrites stale/scraped slots + scoring when it lands
    await ensureNflState();
    state.seasonStatus = state.players.length + ' players · wk ' + state.seasonWeek +
      (state.byesActive ? '' : ' (preseason)');
    scrapeTick();
    if (!state.scrapeTimer) state.scrapeTimer = setInterval(scrapeTick, SCRAPE_MS);
    if (!state.pollTimer) {
      state.pollTimer = setInterval(() => {
        fetchTrending();
        fetchSeasonStats();
      }, SEASON_POLL_MS);
    }
    fetchInjuries();
    fetchTrending();
    fetchSeasonStats();
    render();
  }
  let lastHref = null;
  function onUrlChange() {
    const lid = detectLeagueId();
    if (lid) {
      if (lid !== state.leagueId) initForLeague(lid);
    } else if (state.leagueId) {
      state.leagueId = null;
      destroyPanel();
    }
  }
  async function main() {
    await loadPlayers();
    refreshJackBoards();
    if (MOCK && MOCK.vegas) {
      applyLiveVegas(MOCK.vegas.gameTotals);
      buildSchedule(MOCK.vegas.gameTotals);
      state.wkPropsAll = MOCK.vegas.weeklyProps || null;
      window.BETTING_2026 = MOCK.vegas; // season-sim engine reads gameTotals here
    } else {
      fetchJson('https://www.myfantasyfootball.co/data/betting_lines_2026.json?t=' + Date.now())
        .then((d) => {
          const n = applyLiveVegas(d.gameTotals);
          buildSchedule(d.gameTotals);
          state.wkPropsAll = d.weeklyProps || null;
          window.BETTING_2026 = d; // season-sim engine (SIMS tab) reads gameTotals here
          if (n) console.log('[MFF/Yahoo] live Vegas overlay: ' + n + ' SOS records refreshed');
          render();
        }).catch(() => {});
    }
    gateInit(() => { try { render(); } catch (_) {} });
    lastHref = location.href;
    onUrlChange();
    setInterval(() => {
      if (location.href === lastHref) return;
      lastHref = location.href;
      onUrlChange();
    }, URL_WATCH_MS);
  }

  window.__mffYahoo = { state, render, initForLeague, scrapeTeamPage, scrapePlayersPage,
    wkVal, kickerProjFor, dstProjFor, optimalLineup, waiverRecs, seasonLineupCalc };
  main();
})();
