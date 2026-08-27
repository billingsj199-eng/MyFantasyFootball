// MFF Sleeper Draft Helper — sidebar UI + live draft tracking.
// Unlike the Underdog helper (DOM ribbon scraping), this polls Sleeper's
// public read-only API: /v1/draft/<id> + /v1/draft/<id>/picks. Picks carry
// exact player_id + draft_slot + picked_by, so attribution never guesses.
(() => {
  'use strict';
  if (window.__mffSleeper) return;

  // --- Live Vegas overlay (v0.10.4) ----------------------------------------
  // data/playoff_sos_2026.js is a static snapshot; refresh its gameTotal/
  // teamSpread/impliedTotal fields from the site's live betting JSON (via the
  // background fetch proxy). rank/label/color stay bundled — the 5-signal
  // blend lives in the site's app.js. Fails silently offline.
  function _mffApplyLiveVegas(gameTotals) {
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
            if (typeof g.total === 'number') {
              rec.impliedTotal = (g.total - rec.teamSpread) / 2;
            }
          }
          updated++;
        });
      });
    });
    return updated;
  }
  try {
    chrome.runtime.sendMessage(
      { type: 'mffFetch',
        url: 'https://www.myfantasyfootball.co/data/betting_lines_2026.json?t=' + Date.now() },
      (res) => {
        if (chrome.runtime.lastError || !res || !res.ok || !res.data) return;
        window.BETTING_2026 = res.data; // season-sim engine (PICKS tab) reads gameTotals here
        const n = _mffApplyLiveVegas(res.data.gameTotals);
        buildSchedule(res.data.gameTotals); // full-season week→opponent map for season mode
        state.wkPropsAll = res.data.weeklyProps || null; // site W1+ prop boards → weekly projections
        if (n) console.log('[MFF/Sleeper] live Vegas overlay: ' + n + ' SOS records refreshed'
          + (res.data.generatedAt ? ' (site lines from ' + res.data.generatedAt + ')' : ''));
      });
    // Site consensus weekly projections (Sleeper h/p/s + ESPN/FP e/f arrays) —
    // reference row in the expanded player profile, never a scoring input.
    chrome.runtime.sendMessage(
      { type: 'mffFetch',
        url: 'https://www.myfantasyfootball.co/data/weekly_projections.json?t=' + Date.now() },
      (res) => {
        if (chrome.runtime.lastError || !res || !res.ok || !res.data || !res.data.players) return;
        state.wkConsensus = res.data;
        state.wkConsensusIdx = null; // rebuilt lazily on first lookup
      });
    // Sim Lab export (site sim_proj_2026.json — same file the site's PROJ
    // columns read): rest-of-season seasonPpg + per-week rows, refreshed on
    // the site daily + ~30 min before kickoffs, frozen at kickoff. THE
    // projection source wherever a row exists (Jack 2026-08-26); the Clay /
    // engine / props chain below stays as the fallback. League-custom
    // scoring is re-applied as an additive delta off the Clay components.
    chrome.runtime.sendMessage(
      { type: 'mffFetch',
        url: 'https://www.myfantasyfootball.co/data/sim_proj_2026.json?t=' + Date.now() },
      (res) => {
        if (chrome.runtime.lastError || !res || !res.ok || !res.data || !res.data.weeks) return;
        state.simProj = res.data;
        state.simProjIdx = null;
        // pPg was already rescored before this landed — re-run so the
        // season numbers flip to the sim values.
        if (state.players && state.players.length) applyLeagueScoring(state.leagueScoring);
        console.log('[MFF/Sleeper] Sim Lab projections loaded (wk ' + res.data.currentWeek + ')');
      });
  } catch (_) {}

  const API = 'https://api.sleeper.app/v1';
  const POLL_MS = 2500;
  const URL_WATCH_MS = 1500;
  const MOCK = window.__MFF_MOCK || null;

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
      '<div style="font-weight:800;font-size:13px;margin:6px 0">MFF SLEEPER HELPER — Premium</div>' +
      '<div style="color:#9aa0ab;margin-bottom:10px">' + (signed
        ? 'Signed in as ' + String(u.email).replace(/[&<>"]/g, '') + ' — a Premium account is required.'
        : 'Sign in at myfantasyfootball.co with a Premium account to unlock.') + '</div>' +
      '<a href="https://www.myfantasyfootball.co" target="_blank" rel="noopener noreferrer" style="display:inline-block;background:#00ceb8;color:#fff;border-radius:6px;padding:7px 14px;font-weight:700;text-decoration:none;font-size:12px">' +
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
    byId: Object.create(null),
    byName: Object.create(null),      // "norm|POS" -> player
    byNameLoose: Object.create(null), // "norm" -> player (best rank wins)
    pickAssets: [],
    tiers: {},   // Jack's tier boundaries per rank field: {rank/jSf/jDy/jDsf: [{a,l,n}]}
    exportedAt: '',
    draftId: null,
    draft: null,
    picks: [],
    draftedIds: new Set(),
    draftedKeys: new Set(),
    manualDrafted: new Set(),
    manualMine: new Set(),
    searchQ: '',
    myRoster: [],
    mySlot: null,
    myUserId: null,
    username: '',
    tracking: false,
    rankSource: 'ktc',
    mode: 'dyn_sf',
    modeManual: false,
    modeDetected: null,
    posFilter: 'ALL',
    tab: 'draft',
    sortVor: false,
    notify: true,
    league: null,
    scoringLabel: 'PPR',
    userNames: {},
    expandedKey: null,
    statusMsg: 'Loading players…',
    pollTimer: null,
    // ---- season (regular) mode ----
    appMode: 'draft',        // 'draft' | 'season'
    seasonLeagueId: null,
    seasonLeague: null,
    seasonRosters: [],
    seasonMatchups: [],
    myLeagueRosterId: null,
    seasonWeek: 1,
    wkConsensus: null,       // site weekly_projections.json payload (Sleeper/ESPN/FP)
    wkConsensusIdx: null,    // lazy norm-name index into wkConsensus.players
    byesActive: false,
    nflState: null,
    slMeta: {},              // sid -> {n, pos, tm, inj} from Sleeper /players/nfl
    schedule: {},            // TEAM -> wk -> {opp, home, total, implied} from site Vegas lines
    wkPropsAll: null,        // site weeklyProps: {"1": {name: {UD:{...}, PP:{...}}}}
    seasonStats: null,       // {upToWk, byId: {sid: {ppr, half, std, gp}}} — 2026 actuals
    trendAdds: {},           // sid -> 24h add count
    myLeagues: [],
    seasonTab: 'lineup',
    seasonPosFilter: 'ALL',
    seasonTeamSrc: 'ktc',    // TEAM tab value source: ktc | jack | fp | sl
    seasonPollTimer: null,
    seasonStatus: 'Loading league…',
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

  // Sleeper spells some players differently than the site board (Sleeper says
  // "Kenny Gainwell", the board says "Kenneth Gainwell") — with no alias step
  // the name paths can't match, so a drafted player never leaves the available
  // list and on-page pills go blank. Mirrors ALIASES in
  // export_sleeper_extension_data.py, applied in BOTH directions so either
  // spelling resolves.
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
  // ---------- Sim Lab projection lookups (state.simProj) ----------
  // seasonPpg / weeks rows are [half, ppr, std(, boom, bust)] keyed by CLAY
  // names (DST rows keyed DST_<abbr>). Index by norm() with the ALIASES fold
  // so Kenneth/Ken Walker style variants resolve either way.
  function simProjIdx() {
    if (!state.simProj) return null;
    if (!state.simProjIdx) {
      const fold = (m) => {
        for (const a of Object.keys(ALIASES)) {
          if (m[a] === undefined) {
            for (const alt of ALIASES[a]) { if (m[alt] !== undefined) { m[a] = m[alt]; break; } }
          }
        }
        return m;
      };
      const ix = { season: Object.create(null), weeks: Object.create(null) };
      const sp = state.simProj.seasonPpg || {};
      for (const k of Object.keys(sp)) ix.season[norm(k)] = sp[k];
      fold(ix.season);
      const wks = state.simProj.weeks || {};
      for (const w of Object.keys(wks)) {
        const m = Object.create(null);
        for (const k of Object.keys(wks[w])) m[norm(k)] = wks[w][k];
        ix.weeks[w] = fold(m);
      }
      state.simProjIdx = ix;
    }
    return state.simProjIdx;
  }
  function simKeyFor(p) {
    if (p.s === 'DST') return 'dst_' + String(p.sTm || p.t || '').toLowerCase();
    return norm(p.n);
  }
  // League-scoring delta vs the sim's PPR frame, per game — additive and
  // exact for rec value / pass-TD value / TE premium (sim stat mix = Clay's).
  function simLeagueDeltaPg(p) {
    if (p.cPts == null || !p.cGm || !state.scoringVals) return 0;
    const sv = state.scoringVals;
    return ((sv.recPts - 1) * (p.cRec || 0) + (sv.passTd - 4) * (p.cPtd || 0) +
      ((sv.teBonus && p.s === 'TE') ? sv.teBonus * (p.cRec || 0) : 0)) / p.cGm;
  }

  // Single lookup path for every Sleeper-name → site-player match (pick
  // metadata, draft-board rows, roster rows, trade tokens).
  function findPlayer(name, pos) {
    const pk = pos === 'DEF' || pos === 'D/ST' ? 'DST' : (pos || '');
    const tryName = (nm) =>
      state.byName[nm + '|' + pk] || state.byNameLoose[nm] || null;
    const nm = norm(name);
    let p = tryName(nm);
    if (p) return p;
    for (const alt of ALIASES[nm] || []) {
      p = tryName(alt);
      if (p) return p;
    }
    if (pk === 'DST') return state.byName[norm(name + ' D/ST') + '|DST'] || null;
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

  // ---------- API via background service worker (content scripts hit page CORS) ----------
  // v0.29.4: reloading/updating the extension at chrome://extensions orphans
  // content scripts already injected into open tabs — chrome.runtime evaporates
  // and every sendMessage throws "Cannot read properties of undefined". Detect
  // the dead context and surface a plain-English fix instead of the TypeError.
  const DEAD_CTX_MSG = 'Extension was updated — refresh this tab';
  function extAlive() {
    try { return !!(chrome && chrome.runtime && chrome.runtime.id); } catch (e) { return false; }
  }
  function bgFetch(url) {
    return new Promise((resolve, reject) => {
      if (!extAlive()) return reject(new Error(DEAD_CTX_MSG));
      try {
        chrome.runtime.sendMessage({ type: 'mffFetch', url }, (resp) => {
          if (chrome.runtime.lastError) return reject(new Error(chrome.runtime.lastError.message));
          if (!resp || !resp.ok) return reject(new Error(resp ? resp.error : 'no response'));
          resolve(resp.data);
        });
      } catch (e) { reject(extAlive() ? e : new Error(DEAD_CTX_MSG)); }
    });
  }
  function api(path) {
    if (MOCK && MOCK.api) return Promise.resolve(MOCK.api(path));
    // v0.29.5: cache-buster. api.sleeper.app sits behind Cloudflare with
    // s-maxage=15 + stale-while-revalidate=300, so a plain GET can return
    // picks up to 15s stale (5 MINUTES under SWR) no matter how fast we
    // poll — the draft board (websocket-driven) races ahead of the helper.
    // A unique query string per request skips the CDN cache entirely.
    const sep = path.indexOf('?') >= 0 ? '&' : '?';
    return bgFetch(API + path + sep + '_=' + Date.now());
  }

  // ---------- live Jack's boards (same Firestore doc the export script reads) ----------
  const FIRESTORE_URL =
    'https://firestore.googleapis.com/v1/projects/jackb933-website/databases/(default)' +
    '/documents/rankings/jacks-official?key=AIzaSyD9D_Rhb5hEpz2cBWqQr7hcFCDoluwq6uY';
  async function refreshJackBoards() {
    if (MOCK) return; // harness uses baked boards
    // PREMIUM (v0.28.2): the bundle only carries the free top-36 slice of
    // Jack's boards — the live full-board pull is premium-only. Read the
    // synced user straight from storage: the gate's async boot read may not
    // have landed in _gateUser yet the first time this runs.
    try {
      const gu = await store.get(['mff_user']);
      const u = (gu && gu.mff_user) || _gateUser;
      if (!(u && u.premium && u.syncedAt && (Date.now() - u.syncedAt) < GATE_TTL_MS)) return;
    } catch (e) { return; }
    try {
      const doc = await bgFetch(FIRESTORE_URL);
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
        state.statusMsg = state.players.length + ' players · boards live' + (upd ? ' ' + upd : '');
        if (state.tracking || state.appMode === 'season') render(); else renderStatusOnly();
      }
    } catch (e) { /* baked boards from players.json stay in effect */ }
  }

  // v0.26.1: long-lived tabs never re-fetched boards — re-pull when the tab is
  // refocused after 5+ minutes hidden ("saved on the site, came back here").
  let _boardsFetchedAt = Date.now();
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState !== 'visible') return;
    if (Date.now() - _boardsFetchedAt < 5 * 60 * 1000) return;
    _boardsFetchedAt = Date.now();
    refreshJackBoards();
  });
  // Premium sync can land AFTER boot (user opens the site in another tab) —
  // pull the live boards the moment the gate user turns premium instead of
  // leaving the sliced bundle in effect until the next refocus.
  try {
    chrome.storage.onChanged.addListener((ch, area) => {
      if (area !== 'local' || !ch.mff_user) return;
      const nu = ch.mff_user.newValue, was = ch.mff_user.oldValue;
      if (nu && nu.premium && !(was && was.premium)) { _boardsFetchedAt = Date.now(); refreshJackBoards(); }
    });
  } catch (_) {}

  // Bridge-shipped full boards (board-gating Phase B): a premium site session
  // writes versionBoards.jacks into chrome.storage 'mff_jacks_boards' via
  // mff-page-user/mff-bridge. Once Phase C rules-gates the official doc, the
  // direct Firestore read above 403s and THIS is the premium path to the full
  // board. The live fetch still wins when it works — it runs after this on
  // boot and re-runs on refocus/premium-unlock.
  async function applyBridgeJackBoards(v) {
    try {
      if (!v || !v.boards) return;
      if (!(v.syncedAt && (Date.now() - v.syncedAt) < 7 * 24 * 60 * 60 * 1000)) return; // stale ship
      const gu = await store.get(['mff_user']);
      const u = (gu && gu.mff_user) || _gateUser;
      if (!(u && u.premium && u.syncedAt && (Date.now() - u.syncedAt) < GATE_TTL_MS)) return;
      const byNorm = {};
      for (const p of state.players) (byNorm[norm(p.n)] = byNorm[norm(p.n)] || []).push(p);
      let applied = 0;
      for (const key of ['rank', 'jSf', 'jDy', 'jDsf']) {
        const order = v.boards[key];
        if (!Array.isArray(order) || !order.length) continue;
        order.forEach((name, i) => {
          const list = byNorm[norm(name)];
          if (list) for (const p of list) { p[key] = i + 1; applied++; }
        });
        const tl = v.tiers && v.tiers[key];
        if (Array.isArray(tl) && tl.length) state.tiers[key] = tl;
      }
      if (applied) {
        state.statusMsg = state.players.length + ' players · boards synced from site';
        if (state.tracking || state.appMode === 'season') render(); else renderStatusOnly();
      }
    } catch (_) {}
  }
  try {
    chrome.storage.onChanged.addListener((ch, area) => {
      if (area === 'local' && ch.mff_jacks_boards) applyBridgeJackBoards(ch.mff_jacks_boards.newValue);
    });
  } catch (_) {}

  // ---------- players ----------
  async function loadPlayers() {
    let data;
    if (MOCK && MOCK.players) {
      data = MOCK.players;
    } else {
      const url = chrome.runtime.getURL('data/players.json');
      data = await (await fetch(url)).json();
    }
    state.players = data.players || [];
    applyLeagueScoring(null); // full-PPR/4-pt baseline until the league loads
    state.pickAssets = data.pickAssets || [];
    state.tiers = data.tiers || {}; // Jack's tier boundaries per rank field
    state.exportedAt = data.exported_at || '';
    for (const p of state.players) {
      if (p.sid) state.byId[p.sid] = p;
      const k = keyOf(p);
      if (!state.byName[k]) state.byName[k] = p;
      const loose = norm(p.n);
      if (!state.byNameLoose[loose]) state.byNameLoose[loose] = p;
    }
    state.statusMsg = state.players.length + ' players · data ' + state.exportedAt;
  }

  // ---------- draft detection ----------
  function detectDraftId() {
    if (MOCK && MOCK.draftId) return MOCK.draftId;
    const m = location.href.match(/\/draft\/(?:[a-z_]+\/)?(\d{10,})/i);
    return m ? m[1] : null;
  }
  function detectLeagueId() {
    if (MOCK) return null;
    const m = location.href.match(/\/leagues\/(\d{10,})/i);
    return m ? m[1] : null;
  }

  // ---------- pick order math ----------
  function slotForPick(pickNo) {
    const d = state.draft;
    if (!d || !d.settings) return null;
    const t = d.settings.teams;
    const round = Math.ceil(pickNo / t);
    const idx = (pickNo - 1) % t; // 0-based within round
    if (d.type === 'linear') return idx + 1;
    const rev = d.settings.reversal_round || 0;
    let forward = round % 2 === 1;
    if (rev > 0 && round >= rev) forward = !forward;
    return forward ? idx + 1 : t - idx;
  }
  function picksUntilMine() {
    const d = state.draft;
    if (!d || !d.settings || !state.mySlot || d.type === 'auction') return null;
    const total = d.settings.teams * d.settings.rounds;
    const next = state.picks.length + 1;
    for (let p = next; p <= total; p++) {
      if (slotForPick(p) === state.mySlot) return p - next;
    }
    return null;
  }
  function currentRound() {
    const d = state.draft;
    if (!d || !d.settings) return 1;
    return Math.min(d.settings.rounds, Math.ceil((state.picks.length + 1) / d.settings.teams));
  }
  // Overall number of my pick AFTER the one I'm currently making — the
  // "will he still be there?" horizon for the leapfrog guard.
  function myNextPickOverall() {
    const d = state.draft;
    if (!d || !d.settings || !state.mySlot || d.type === 'auction') return null;
    const total = d.settings.teams * d.settings.rounds;
    let found = 0;
    for (let p = state.picks.length + 1; p <= total; p++) {
      if (slotForPick(p) === state.mySlot) {
        found++;
        if (found === 2) return p;
      }
    }
    return null;
  }

  // ---------- pick processing (full idempotent rebuild — survives undo) ----------
  function matchPick(pk) {
    if (pk.player_id && state.byId[pk.player_id]) return state.byId[pk.player_id];
    const md = pk.metadata || {};
    const nm = ((md.first_name || '') + ' ' + (md.last_name || '')).trim();
    if (!nm) return null;
    // DEF: our DST entries are named "Houston Texans D/ST"; metadata says
    // "Houston Texans" — findPlayer's DST branch re-appends the suffix.
    return findPlayer(nm, md.position || '');
  }
  function isMinePick(pk) {
    if (state.myUserId && pk.picked_by) return pk.picked_by === state.myUserId;
    return state.mySlot != null && pk.draft_slot === state.mySlot;
  }
  function processPicks(picks) {
    state.picks = picks;
    state.draftedIds = new Set();
    state.draftedKeys = new Set();
    state.myRoster = [];
    for (const pk of picks) {
      if (pk.player_id) state.draftedIds.add(String(pk.player_id));
      const p = matchPick(pk);
      if (p) state.draftedKeys.add(keyOf(p));
      if (isMinePick(pk)) {
        const md = pk.metadata || {};
        state.myRoster.push({
          p,
          name: p ? p.n : ((md.first_name || '') + ' ' + (md.last_name || '')).trim() || String(pk.player_id),
          pos: p ? p.s : (md.position === 'DEF' ? 'DST' : md.position || '?'),
          pickNo: pk.pick_no,
        });
      }
    }
    // Manually forced roster adds (API missed / offline picks)
    for (const k of state.manualMine) {
      const p = state.byName[k];
      if (!p || state.myRoster.some((r) => r.p === p)) continue;
      state.draftedKeys.add(k);
      state.myRoster.push({ p, name: p.n, pos: p.s, pickNo: null, manual: true });
    }
  }

  // ---------- polling ----------
  async function pollOnce() {
    if (!state.draftId) return;
    try {
      const picks = await api('/draft/' + state.draftId + '/picks');
      if (Array.isArray(picks)) {
        const changed = picks.length !== state.picks.length;
        processPicks(picks);
        if (changed || !state._rendered) render();
      }
    } catch (e) {
      state.statusMsg = 'API error: ' + e.message;
      renderStatusOnly();
    }
  }
  function startPolling() {
    stopPolling();
    state.pollTimer = setInterval(pollOnce, POLL_MS);
    pollOnce();
  }
  function stopPolling() {
    if (state.pollTimer) { clearInterval(state.pollTimer); state.pollTimer = null; }
  }

  // ---------- league-scoring adjustment ----------
  // Clay's cPts is FULL PPR with 4-pt passing TDs. Re-score pPg/szn to the
  // league's actual scoring_settings (rec + pass_td are the two that move
  // projections meaningfully). VOR/upside/ceiling stay export-baked (½PPR).
  function applyLeagueScoring(scoring) {
    state.leagueScoring = scoring || null; // full rules: K distance buckets + DST values
    const recPts = scoring && scoring.rec != null ? scoring.rec : 1;
    const passTd = scoring && scoring.pass_td != null ? scoring.pass_td : 4;
    const teBonus = (scoring && scoring.bonus_rec_te) || 0; // TE premium
    state.scoringLabel =
      (recPts === 1 ? 'PPR' : recPts === 0.5 ? '½PPR' : recPts === 0 ? 'STD' : recPts + '/rec') +
      (passTd !== 4 ? ' · ' + passTd + 'pt paTD' : '') +
      (teBonus ? ' · TEP+' + teBonus : '');
    state.scoringVals = { recPts, passTd, teBonus };
    for (const p of state.players) {
      if (p.cPts == null || !p.cGm) continue;
      let adj = p.cPts + (recPts - 1) * (p.cRec || 0) + (passTd - 4) * (p.cPtd || 0);
      if (teBonus && p.s === 'TE') adj += teBonus * (p.cRec || 0);
      p.szn = Math.round(adj * 10) / 10;
      p.pPg = Math.round((adj / p.cGm) * 10) / 10;
      // SIM-FIRST: Sim Lab rest-of-season PPG (PPR frame) + this league's
      // additive scoring delta replaces the flat Clay season/gm number.
      const _six = simProjIdx();
      if (_six && p.s !== 'K' && p.s !== 'DST') {
        const sp = _six.season[simKeyFor(p)];
        if (sp && typeof sp[1] === 'number') {
          p.pPg = Math.round((sp[1] + simLeagueDeltaPg(p)) * 10) / 10;
          p.szn = Math.round(p.pPg * p.cGm * 10) / 10;
        }
      }
      // scDelta = per-game PPG shift this league's scoring gives the player
      // vs the ½PPR / 4-pt-paTD baseline the rank sources assume. Feeds the
      // Recommended score so full-PPR bumps reception hogs, STD fades them,
      // and TE premium lifts TEs.
      p.scDelta = Math.round((((recPts - 0.5) * (p.cRec || 0) + (passTd - 4) * (p.cPtd || 0) +
        ((teBonus && p.s === 'TE') ? teBonus * (p.cRec || 0) : 0)) / p.cGm) * 10) / 10;
    }
  }

  // ---------- modes ----------
  // Default rank source + QB-need floor per format. User can override both.
  const MODES = {
    dyn_sf:  { label: 'Dynasty SF',  src: 'ktc',  qbFloor: 2 },
    dyn_1qb: { label: 'Dynasty 1QB', src: 'ktc',  qbFloor: 1 },
    re_sf:   { label: 'Redraft SF',  src: 'jack', qbFloor: 2 },
    re_1qb:  { label: 'Redraft 1QB', src: 'jack', qbFloor: 1 },
  };
  function applyMode(mode, manual) {
    if (!MODES[mode]) return;
    state.mode = mode;
    if (manual) state.modeManual = true;
    state.rankSource = MODES[mode].src;
  }
  // Sleeper tells us the format: slots_super_flex / slots_qb on the draft
  // settings, scoring_type like "dynasty_2qb", league.settings.type (1 keeper,
  // 2 dynasty) as the fallback for league drafts.
  async function detectMode() {
    const d = state.draft;
    if (!d) return null;
    const st = d.settings || {};
    const scoring = ((d.metadata && d.metadata.scoring_type) || '').toLowerCase();
    const sf = (st.slots_super_flex || 0) > 0 || (st.slots_qb || 0) >= 2 || /2qb|superflex/.test(scoring);
    let dynasty = /dynasty|keeper/.test(scoring);
    if (!dynasty && state.league) {
      dynasty = !!(state.league.settings && state.league.settings.type >= 1);
    }
    return (dynasty ? 'dyn' : 're') + '_' + (sf ? 'sf' : '1qb');
  }

  // ---------- recommendations ----------
  // Jack's / FP / Sleeper ranks come in four flavors; the mode picks the column.
  // The mode picks the format FIRST; every source below resolves to that
  // format's column. The source dropdown is purely "whose rankings".
  const MODE_KEYS = {
    dyn_sf:  { ktc: 'ktcSf',  jack: 'jDsf', fp: 'fpDsf', sl: 'slDsf', adp: 'sa',  vor: 'vorSf', up: 'upSf' },
    dyn_1qb: { ktc: 'ktc1qb', jack: 'jDy',  fp: 'fpDy',  sl: 'slDy',  adp: 'da',  vor: 'vor',   up: 'up'   },
    re_sf:   { ktc: 'ktcSf',  jack: 'jSf',  fp: 'fpSf',  sl: 'slSf',  adp: 'sfa', vor: 'vorSf', up: 'upSf' },
    re_1qb:  { ktc: 'ktc1qb', jack: 'rank', fp: 'fpR',   sl: 'slR',   adp: 'a',   vor: 'vor',   up: 'up'   },
  };
  function modeKeys() { return MODE_KEYS[state.mode] || MODE_KEYS.dyn_sf; }
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
    // JM prospect-model score (0-100, format-independent) — baked into
    // players.json by export_sleeper_extension_data.py from data/jm_scores.json
    // (scripts/pull_jm_scores.py dumps it off the live site). Sorting by it is
    // the rookie-draft view: vets keep their draft-class grade.
    jm:   { label: 'JM Score',     get: (p) => p.jmS,              desc: true },
  };
  // older prefs stored raw field names / format-specific KTC ids
  const SOURCE_MIGRATE = { rank: 'jack', fpR: 'fp', slR: 'sl', ktcSf: 'ktc', ktc1qb: 'ktc' };
  function isDrafted(p) {
    const k = keyOf(p);
    return (p.sid && state.draftedIds.has(String(p.sid))) ||
      state.draftedKeys.has(k) || state.manualDrafted.has(k);
  }
  // OUT FOR SEASON: the site's IR flag hides a player from the redraft /
  // best ball / superflex / weekly boards but deliberately KEEPS him in
  // dynasty (he still has trade value), so mirror that split rather than
  // dropping him from the data. Search still finds him, same as the site.
  function isIrHidden(p) { return !!p.ir && state.mode.indexOf('dyn') !== 0; }
  function availablePlayers() {
    return state.players.filter((p) => !isDrafted(p) && !isIrHidden(p));
  }
  // ADP value tags vs the current pick, fall-based: a player still on the
  // board past his ADP is FALLING (STEAL/Value); a player whose ADP is well
  // after the current pick would be a market reach — don't reach 20+ picks,
  // you can very likely get him on a later turn (Reach/Stretch).
  function adpTag(p) {
    const adp = p[modeKeys().adp];
    if (adp == null || !state.draft || !state.draft.settings) return null;
    const t = state.draft.settings.teams || 12;
    const diff = adp - (state.picks.length + 1); // +ve = market drafts him later
    if (diff <= -2 * t) return 'STEAL';   // fell 2+ rounds past ADP
    if (diff <= -t) return 'Value';       // fell a full round
    if (diff >= 20) return 'Reach';       // 20+ picks early vs market
    if (diff >= 12) return 'Stretch';     // roughly a round early
    return null;
  }
  // STACK = QB↔WR/TE pairing with my roster; TEAM = softer same-team overlap.
  function stackInfo(p) {
    if (!p.sTm) return null;
    const mates = state.myRoster.filter((r) => r.p && r.p.sTm === p.sTm);
    if (!mates.length) return null;
    const hasQB = mates.some((r) => r.pos === 'QB');
    const hasCatcher = mates.some((r) => r.pos === 'WR' || r.pos === 'TE');
    const names = mates.map((m) => m.name);
    if (((p.s === 'WR' || p.s === 'TE') && hasQB) || (p.s === 'QB' && hasCatcher)) {
      return { type: 'stack', names };
    }
    return { type: 'team', names };
  }
  // Greedy best-lineup PPG from the draft's actual roster slots (½ PPR Clay).
  function starterProjPPG() {
    const st = (state.draft && state.draft.settings) || {};
    const pool = state.myRoster
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
    take(['QB'], st.slots_qb); take(['RB'], st.slots_rb);
    take(['WR'], st.slots_wr); take(['TE'], st.slots_te);
    take(['RB', 'WR', 'TE'], st.slots_flex);
    take(['QB', 'RB', 'WR', 'TE'], st.slots_super_flex);
    take(['WR', 'RB'], st.slots_wrrb_flex);
    take(['WR', 'TE'], st.slots_rec_flex);
    take(['K'], st.slots_k);
    return Math.round(total * 10) / 10;
  }
  function sortedAvailable() {
    const src = SOURCES[state.rankSource];
    const avail = availablePlayers().filter(
      (p) => state.posFilter === 'ALL' || p.s === state.posFilter
    );
    avail.sort((a, b) => {
      const va = src.get(a), vb = src.get(b);
      if (va == null && vb == null) return a.rank - b.rank;
      if (va == null) return 1;
      if (vb == null) return -1;
      return src.desc ? vb - va : va - vb;
    });
    if (state.sortVor) {
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
  // (sortedAvailable's comparator is duplicated in sortListBySource for
  // arbitrary lists — keep the two in sync if thresholds change.)
  function rosterCounts() {
    const c = { QB: 0, RB: 0, WR: 0, TE: 0, K: 0, DST: 0 };
    for (const r of state.myRoster) if (c[r.pos] != null) c[r.pos]++;
    return c;
  }
  // Draft-capital-weighted position counts: a round-1 pick "fills" a position
  // far more than a round-9 dart. quality = 1.0 through round 2, declining
  // ~7%/round to a 0.4 floor; manual adds (unknown pick) count 0.7. So three
  // round-6+ QBs ≈ 1.8 "real" QBs — the position still wants quality even
  // though the raw count looks full.
  function effRosterCounts() {
    const t = (state.draft && state.draft.settings && state.draft.settings.teams) || 12;
    const c = { QB: 0, RB: 0, WR: 0, TE: 0, K: 0, DST: 0 };
    for (const r of state.myRoster) {
      if (c[r.pos] == null) continue;
      const rd = r.pickNo ? Math.ceil(r.pickNo / t) : null;
      c[r.pos] += rd == null ? 0.7 : Math.max(0.4, Math.min(1, 1.14 - 0.07 * rd));
    }
    return c;
  }
  // Draft-capital VALUE model: every pick carries trade-chart-style value
  // v(n) (~60 at 1.01 decaying to a ~4-pt floor); each position banks the
  // value of the picks spent on it. Need is then VALUE invested vs the
  // format's target share of everything spent so far — not a body count.
  // A room of three round-9 QBs banks less than one round-1 QB, so QB stays
  // under-invested exactly as it should.
  function pickValue(n) { return 60 * Math.exp(-n / 85) + 4; }
  // Target share of total draft capital per position. SF pours real capital
  // into QB; 1QB barely does.
  const CAPITAL_SHARE = {
    sf:  { QB: 0.30, RB: 0.21, WR: 0.33, TE: 0.12 },
    one: { QB: 0.11, RB: 0.28, WR: 0.45, TE: 0.12 },
  };
  // League-adjusted capital targets: start from the format base, tilt toward
  // the positions the lineup actually starts (3WR / multi-flex builds want
  // more WR capital) and toward the scoring (full PPR favors WRs, STD favors
  // RBs, TE premium favors TEs), then renormalize — so a WR-heavy PPR lineup
  // pulls its extra share out of QB and TE.
  function capitalShares() {
    const s = Object.assign({}, CAPITAL_SHARE[state.mode.endsWith('_sf') ? 'sf' : 'one']);
    const st = (state.draft && state.draft.settings) || {};
    // Lineup tilt vs the classic 2RB/2WR/1FLEX/1TE baseline (skip when the
    // draft doesn't carry lineup slots, e.g. mocks).
    if (st.slots_rb || st.slots_wr) {
      const flex = (st.slots_flex || 0) + (st.slots_wrrb_flex || 0);
      const recFlex = st.slots_rec_flex || 0;
      s.RB *= ((st.slots_rb || 2) + 0.45 * flex) / 2.45;
      s.WR *= ((st.slots_wr || 2) + 0.55 * flex + 0.5 * recFlex) / 2.55;
      s.TE *= (st.slots_te || 1) + 0.15 * recFlex;
    }
    const sv = state.scoringVals || {};
    const rec = sv.recPts != null ? sv.recPts : 1;
    if (rec >= 0.75) { s.WR *= 1.08; s.RB *= 0.94; }       // full PPR
    else if (rec <= 0.25) { s.RB *= 1.1; s.WR *= 0.92; }    // STD-ish
    if (sv.teBonus) s.TE *= 1.15;                           // TE premium
    const tot = s.QB + s.RB + s.WR + s.TE;
    for (const k in s) s[k] = s[k] * 0.96 / tot;
    return s;
  }
  // Per-position fraction of the target still missing: +1 = nothing banked,
  // 0 = on target, negative = over-invested.
  // Positional QUALITY — what number by position you own, NOT what round you
  // spent (Jack, 2026-08-05): "QB3 even if taken in round 6 should be treated
  // like a premium, and another QB shouldn't need to be taken. If you take WR2
  // and WR5, WR won't be as important."
  //
  // Each rostered player is weighted by his rank WITHIN his position on the
  // active board — 1st ≈ 1.00, 3rd ≈ 0.72, 6th ≈ 0.43, 12th ≈ 0.16, 24th ≈
  // 0.02 — summed per position and expressed as a share of that position's
  // starters. So QB3 alone fills ~0.72 of a 1-QB requirement, and WR2+WR5
  // fills (0.85 + 0.51) / 2 ≈ 0.68 of a 2-WR requirement. A pile of late
  // bodies at the same COUNT barely registers, which is the whole point.
  const POS_Q_DECAY = 6;
  function posQualityFill() {
    const src = SOURCES[state.rankSource] || SOURCES.jack;
    const byPos = {};
    for (const p of state.players) {
      const v = src.get(p);
      if (v == null) continue;
      (byPos[p.s] = byPos[p.s] || []).push([p, v]);
    }
    const idx = new Map();
    for (const k in byPos) {
      byPos[k].sort((a, b) => (src.desc ? b[1] - a[1] : a[1] - b[1]));
      byPos[k].forEach((e, i) => idx.set(e[0], i + 1));
    }
    const st = (state.draft && state.draft.settings) || {};
    const starters = {
      QB: (st.slots_qb || 0) + (st.slots_super_flex || 0) || 1,
      RB: st.slots_rb || 1, WR: st.slots_wr || 1, TE: st.slots_te || 1,
    };
    const banked = { QB: 0, RB: 0, WR: 0, TE: 0 };
    for (const r of state.myRoster) {
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
    for (const r of state.myRoster) {
      const v = pickValue(r.pickNo || Math.max(1, state.picks.length / 2));
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
  // Format-aware need flags. QB/RB/WR/TE use draft-capital-weighted counts
  // (late-round bodies don't silence a need); K/DST stay raw — a kicker is
  // a kicker.
  // Rank WITHIN position for every player, by the active rank source —
  // shared by the depletion-schedule need check and the need-boost gate.
  function posRankIndex() {
    const src = SOURCES[state.rankSource] || SOURCES.jack;
    const posIdx = new Map();
    const byP = {};
    for (const p of state.players) {
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
  // Position depletion: how many at each position are off the board, counted
  // through isDrafted() over the data pool so id-keyed, name-keyed and
  // manually-marked picks all count the same.
  function draftedPosCounts() {
    const g = { QB: 0, RB: 0, WR: 0, TE: 0 };
    for (const p of state.players) if (g[p.s] != null && isDrafted(p)) g[p.s]++;
    return g;
  }
  function needPositions() {
    const c = rosterCounts();
    const ec = effRosterCounts();
    const rd = currentRound();
    const m = MODES[state.mode];
    const st = (state.draft && state.draft.settings) || {};
    const dynasty = state.mode.startsWith('dyn');
    const need = new Set();
    if (m.qbFloor >= 2) {
      if (ec.QB < 1.9) need.add('QB'); // SF: 2 startable-quality QBs is the floor
    } else if (c.QB < 1 && rd >= (dynasty ? 4 : 6)) {
      need.add('QB');
    }
    // EARLY RB2 WINDOW (Jack, 2026-08-06, redraft only): rounds 3-5 with
    // fewer than 2 RBs rostered is a NEED right now — don't wait for the
    // round-5 capital-weighted check below. Also lets the leapfrog guard
    // honor the RB boost cross-position.
    if (state.mode.indexOf('re_') === 0 && rd >= 3 && rd <= 5 && c.RB < 2) need.add('RB');
    if (rd >= 5 && ec.RB < 2.6) need.add('RB');
    if (rd >= 5 && ec.WR < 3.4) need.add('WR');
    if (rd >= 7 && ec.TE < 0.75) need.add('TE');
    // Only nag about K/DST if this draft actually rosters them, in the last rounds.
    const lateRd = (st.rounds || 15) - 2;
    if ((st.slots_k || 0) > 0 && rd >= lateRd && c.K < 1) need.add('K');
    if ((st.slots_def || 0) > 0 && rd >= lateRd && c.DST < 1) need.add('DST');
    // DEPLETION SCHEDULE (Jack, 2026-08-06, redraft only): every league-
    // size-worth of a position off the board is one "cycle" — after 24 RBs
    // in a 12-man league every team should own 2; after 12 QBs every team
    // should own 1. Sitting under floor(taken / teams) at a position =
    // BEHIND schedule = need, whatever the round; at or above = ahead, and
    // this rule stays quiet. Capped at what a lineup actually uses
    // (starters +1 at the flex positions, bare starters at QB/TE) so a
    // league emptying QBs late can't demand a QB2.
    if (state.mode.indexOf('re_') === 0) {
      const gone = draftedPosCounts();
      const t = st.teams || 12;
      const cap = {
        QB: (st.slots_qb || 0) + (st.slots_super_flex || 0) || 1,
        RB: (st.slots_rb || 1) + 1,
        WR: (st.slots_wr || 1) + 1,
        TE: st.slots_te || 1,
      };
      const posIdx = posRankIndex();
      for (const pos of ['QB', 'RB', 'WR', 'TE']) {
        const expect = Math.min(cap[pos], Math.floor(gone[pos] / t));
        if (!expect) continue;
        if (c[pos] < expect) { need.add(pos); continue; }
        if (pos !== 'RB' && pos !== 'WR') continue;
        // QUALITY-AWARE SCHEDULE (Jack, 2026-08-06: "RB20 and RB21 vs RB3
        // and RB6 — it's not the same"): matching the COUNT isn't enough,
        // your k-th best player at the position has to belong to cycle k —
        // best RB inside the top-teams, 2nd inside 2x teams, etc., with a
        // half-cycle cushion. Two late-cycle bodies leave the need lit until
        // quality catches up. QB/TE skip this — presence is their bar; a
        // quality nag there would fight the backup fade head-on.
        const mine = state.myRoster
          .filter((r) => r.pos === pos && r.p && posIdx.get(r.p))
          .map((r) => posIdx.get(r.p)).sort((a, b) => a - b);
        const behind = mine.length < expect ||
          mine.slice(0, expect).some((rk, i) => rk > (i + 1) * t + t / 2);
        if (behind) need.add(pos);
        // Schedule says AHEAD — every quality slot filled on pace. That
        // overrides the round-based depth nag above (Jack: "it should know
        // if you are behind or ahead" — rounds still considered, but the
        // positional schedule outranks them). Only once the schedule is
        // meaningful (expect >= 2), so the rounds-3-5 RB2 window keeps
        // its say early.
        else if (expect >= 2) need.delete(pos);
      }
    }
    return need;
  }

  // ---------- pick recommendations ----------
  // VOR-gap tiers per position among the available board: tier 1 = the top
  // group; a new tier starts on a 10+ VOR (or 2.5+ ppg) gap between
  // consecutive players. Higher-tier players get a Recommended boost so the
  // last tier-1 RB outranks a tier-3 WR sitting slightly higher on the board.
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

  // Composite of board position (current rank source), format-aware VOR,
  // positional tier (higher tier > lower tier), roster need / open starter
  // slots, league-scoring shift (PPR / pass-TD / TE premium vs the ½PPR
  // baseline the ranks assume), ADP (fallers boosted, 20+ pick reaches faded
  // hard), stacks, and positional cliffs — each contribution doubles as a
  // human-readable reason chip.
  function recommendPicks() {
    const avail = availablePlayers();
    const sortedAll = sortListBySource(avail);
    let board = sortedAll.slice(0, 30);
    if (!board.length) return [];
    const st = (state.draft && state.draft.settings) || {};
    const c = rosterCounts();
    const ec = effRosterCounts();
    const deficits = capitalDeficits();
    const rd = currentRound();
    // Rounds 1-4 are best-player-available: four straight RBs is a legit
    // start and one early RB must NOT fade RB in round 2. The need boost
    // whispers early and reaches full strength by round 8; the over-invest
    // fade is OFF entirely through round 4, full by round 8.
    const dampen = Math.min(1, rd / 8);
    const fadeRamp = rd <= 4 ? 0 : Math.min(1, (rd - 4) / 4);
    const lateRd = (st.rounds || 15) - 2;
    // The ONLY thing that reopens a saturated position: a genuine faller,
    // late. "Serious" = slid 2+ full rounds past his own ADP (the STEAL
    // threshold); "late" = last third, so a round-4 slider can't talk you
    // into a second early TE.
    const lateWindow = rd >= Math.ceil((st.rounds || 15) * 0.66);
    const lateFaller = (q) => lateWindow && adpTag(q) === 'STEAL';
    const qfill = posQualityFill();
    // ADP RELIABILITY DECAY (Jack, 2026-08-05): drafters follow ADP less and
    // less as a draft goes on — late rounds are where people reach for their
    // guys, chase upside and go fully off-board. So every ADP-derived signal
    // gets weighted down as the rounds tick by, until it stops voting entirely
    // and only the board, VOR, tiers, needs and cliffs decide. Full trust
    // through round 6, linear to zero by round 12.
    const adpTrust = Math.max(0, Math.min(1, (12 - rd) / 6));
    // ROSTER LOCK (Jack, 2026-08-05 mock): when the picks you have left only
    // just cover the mandatory slots still empty, there is no decision to make
    // — every remaining pick MUST go to one of them. He hit round 15 of 16
    // with 14/16 rostered, D/ST and K both empty, and the helper was still
    // leading with a QB. Two picks, two forced slots, zero choice.
    const spotsLeft = Math.max(0, (st.rounds || 15) - (state.myRoster || []).length);
    const mustFill = [];
    if ((st.slots_k || 0) > 0 && (c.K || 0) < (st.slots_k || 0)) mustFill.push('K');
    if ((st.slots_def || 0) > 0 && (c.DST || 0) < (st.slots_def || 0)) mustFill.push('DST');
    const rosterLocked = mustFill.length > 0 && spotsLeft <= mustFill.length;
    // Locked = the board IS the forced positions (Jack, 2026-08-06 ESPN
    // mock: 14/16 rostered, K + D/ST empty, and the recs were still QB/RB/WR
    // at −57 to −73 — the −100 lock penalty worked, but K/DST rank ~178+ on
    // his board so they never ENTERED the 30-man board window, and the
    // least-bad skill players topped the list anyway). When every remaining
    // pick is forced, only the forced positions belong on the board at all.
    if (rosterLocked) {
      // Top slice of EACH forced position, not of the merged pool — the
      // board ranks nearly every K above every D/ST (or vice versa), so a
      // single merged top-30 can be one position wall-to-wall.
      let fill = [];
      for (const pos of mustFill) {
        fill = fill.concat(sortListBySource(avail.filter((q) => q.s === pos)).slice(0, 15));
      }
      if (fill.length) board = sortListBySource(fill).slice(0, 30);
    }
    const remStarters = {
      QB: Math.max(0, (st.slots_qb || 0) + (st.slots_super_flex || 0) - c.QB),
      RB: Math.max(0, (st.slots_rb || 0) - c.RB),
      WR: Math.max(0, (st.slots_wr || 0) - c.WR),
      TE: Math.max(0, (st.slots_te || 0) - c.TE),
    };
    const openSlots = ['QB', 'RB', 'WR', 'TE'].filter((k) => remStarters[k] > 0);
    const byPos = {};
    for (const p of board) (byPos[p.s] = byPos[p.s] || []).push(p);
    // Cliff detection needs the FULL pool. byPos stops at 30 players, so the
    // last startable player at a thin position has no successor inside the
    // window and scored no cliff at all — see the cliff block below.
    const byPosAll = {};
    for (const p of sortedAll) (byPosAll[p.s] = byPosAll[p.s] || []).push(p);
    const vk = modeKeys().vor;
    const sv = state.scoringVals || {};
    const tiers = boardTiers(byPos);
    const sfMode = state.mode.endsWith('_sf');
    // Board supply per position: how many above-replacement (VOR > 0) players
    // remain in the WHOLE pool. When a run has emptied a position (SF QB
    // rooms), the survivors get scarcer — boost them.
    const supply = {};
    for (const q of avail) {
      if ((q[vk] || 0) > 0) supply[q.s] = (supply[q.s] || 0) + 1;
    }
    const needSet = needPositions();
    // Board-repair context for the need boost: positional ranks, depletion
    // counts and league size, so a need only boosts schedule-quality fills.
    const _needPosIdx = posRankIndex();
    const _needGone = draftedPosCounts();
    const _needT = st.teams || 12;
    const scored = board.map((p, idx) => {
      let score = Math.max(0, 30 - idx);
      const reasons = [];
      // Roster-fit penalties (capital/quality saturation, backup QB/TE,
      // roster lock, early K/DST) accumulate here so the leapfrog guard can
      // see them — a player the engine has nerfed as "wrong for THIS roster"
      // forfeits guard protection (see leapfrogOk).
      let rosterPen = 0;
      if (idx === 0) reasons.push('Best on board');
      if (p[vk] != null) score += p[vk] / 10;
      // Tier boost: tier 1 +6, tier 2 +3, tier 3+ nothing.
      const tier = tiers.get(p);
      if (tier === 1) { score += 6; reasons.push('Tier 1 ' + p.s); }
      else if (tier === 2) score += 3;
      // Value-invested need (replaces the old body-count need): boost scales
      // with how far the position's banked capital sits below its target
      // share, up to +8; over-invested positions get a small fade.
      const defc = deficits[p.s] != null ? deficits[p.s] : 0;
      const qf = qfill[p.s] != null ? qfill[p.s] : 0;
      // Quality earned at the position throttles the need boost: capital says
      // "you haven't spent here", quality says "but what you do own is elite".
      // QB3 in round 6 is cheap AND premium — the old capital-only model saw
      // only the cheapness and kept shouting QB.
      if (defc > 0.15 && state.myRoster.length >= 2) {
        let b = Math.min(8, 10 * defc) * dampen * Math.max(0, 1 - qf);
        b = Math.round(b * 10) / 10;
        score += b;
        if (b >= 3) reasons.push('Needs ' + p.s + ' value');
      } else if (defc < -0.35 && fadeRamp > 0) {
        // Positional draft-capital saturation. defc is (target − banked)/target,
        // so −1 means the position has banked DOUBLE the capital it should
        // carry. A 2nd-round TE puts TE around −2.8: another TE there is close
        // to dead capital, yet the old flat −4 cap barely dented a +6 tier
        // bonus. Scale the fade with the actual overspend instead, so an early
        // Bowers-style pick shuts the position down while a round-14 body at
        // the same COUNT barely moves it.
        let fade = Math.min(20, -7 * defc) * fadeRamp;
        if (lateFaller(p)) fade *= 0.25;
        score -= fade;
        rosterPen += fade;
        if (fade >= 5) reasons.push(p.s + ' capital full');
      }
      // Positional-quality saturation — the QB3 / WR2+WR5 rule. Independent of
      // the capital fade above (that one is round-spend based and can miss a
      // cheap elite entirely), and it starts biting at 0.6 fill rather than
      // waiting for a full starter set. Same late-faller escape.
      if (qf > 0.5) {
        let qFade = Math.min(30, 45 * (qf - 0.5)) * dampen;
        if (lateFaller(p)) qFade *= 0.25;
        score -= qFade;
        rosterPen += qFade;
        if (qFade >= 5) reasons.push(p.s + ' set — ' + Math.round(qf * 100) + '% quality');
      }
      // EARLY RB2 PUSH (Jack, 2026-08-06, redraft only): rounds 3-5 with
      // fewer than 2 RBs rostered — boost every RB until the second one is
      // in. The value-need boost above ramps to full strength only by round
      // 8, too slow to force this window; the matching needPositions() entry
      // lets the leapfrog guard honor the jump cross-position.
      if (state.mode.indexOf('re_') === 0 && p.s === 'RB' && rd >= 3 && rd <= 5 && c.RB < 2) {
        score += (2 - c.RB) * 5;
        reasons.push(c.RB === 0 ? 'No RB yet — rounds 3-5 window' : 'RB2 window (rounds 3-5)');
      }
      // NEED BOOST (Jack, 2026-08-06): a flagged need isn't just a badge —
      // the algo leans toward filling it. This is how the depletion schedule
      // ("24 RBs gone and you own 1 = behind") reaches the score. Modest, so
      // tiers and value still rule the pick between needed positions. Gated
      // on what's STILL ON BOARD (Jack, same session): the boost goes only
      // to candidates who actually repair the schedule — current-or-next-
      // cycle quality at the position — never to any body wearing the
      // right letters.
      if (needSet.has(p.s)) {
        const pr = _needPosIdx.get(p);
        const bound = (Math.floor((_needGone[p.s] || 0) / _needT) + 1) * _needT + _needT / 2;
        if (pr == null || pr <= bound) { score += 4; reasons.push('NEED ' + p.s); }
      }
      if (remStarters[p.s] > 0) {
        // The LAST unfilled starter slot is worth more than a generic one:
        // every other lineup hole is already covered, so this is the only
        // pick that still changes whether you can field a legal lineup.
        const lastSlot = openSlots.length === 1;
        score += lastSlot ? 7 : 4;
        reasons.push(lastSlot ? 'LAST open slot: ' + p.s : 'Open ' + p.s + ' slot');
      }
      // Superflex QB depth: the format favors hoarding QBs — a 3rd/4th QB
      // still carries starter-insurance + trade value even with the need met.
      // Uses the capital-weighted count, so a room of late-round QBs keeps
      // earning this long after the raw count says "full".
      else if (sfMode && p.s === 'QB' && ec.QB < 3.2 && defc > -0.5) { score += 4; reasons.push('SF QB depth'); }
      // Supply scarcity: few above-replacement players left at the position.
      const sup = supply[p.s] || 0;
      if (sup > 0 && sup <= 3) { score += 5; reasons.push('Only ' + sup + ' startable ' + p.s + (sup === 1 ? '' : 's') + ' left'); }
      else if (sup > 0 && sup <= 6) score += 2.5;
      // League scoring: reception hogs rise in full PPR, sink in STD; TEs
      // rise with TE premium; big-arm QBs move with 6-pt passing TDs.
      if (p.scDelta) {
        score += Math.max(-6, Math.min(6, p.scDelta * 1.5));
        if (p.scDelta >= 1) {
          reasons.push((sv.teBonus && p.s === 'TE' ? 'TEP' : 'Scoring') + ' +' + p.scDelta.toFixed(1) + ' ppg');
        } else if (p.scDelta <= -1) {
          reasons.push('Scoring −' + Math.abs(p.scDelta).toFixed(1) + ' ppg');
        }
      }
      // ADP earns its place in the score for exactly ONE question: will this
      // player still be on the board at your NEXT pick? If the market says
      // yes, don't spend this pick on him — take the scarcer player and come
      // back for him. The old STEAL/Value boosts and Reach/Stretch fades
      // scored ADP as a VALUE signal measured against the CURRENT pick, which
      // is a different question entirely, and they're gone. The tags still
      // render on the cards as information; they just don't move the score.
      // QBs in superflex get half the fade: SF QB runs are streaky enough
      // that "ADP says he lasts" is least reliable exactly at QB.
      const nextPk = myNextPickOverall();
      const padp = p[modeKeys().adp];
      if (nextPk != null && padp != null && padp >= nextPk) {
        // Scales with HOW FAR past your next pick he goes, and always states
        // itself. The old version faded a 4-picks-past player by a flat 5 and
        // pushed no reason at all, so the card gave no hint that the engine
        // already knew he'd probably still be sitting there next turn.
        const fadeMult = (sfMode && p.s === 'QB') ? 0.5 : 1;
        const over = padp - nextPk;
        const fade = Math.min(16, 6 + over * 0.7) * fadeMult * adpTrust;
        score -= fade;
        // Only claim it when it actually cost him something — a decayed-away
        // fade shouldn't put a confident tag on the card.
        if (fade >= 3) reasons.push('Likely there at your next pick');
      }
      // Stacks matter far less in lineup redraft (they're a best-ball /
      // tournament lever) — tiny tiebreaker there, real bonus in dynasty.
      const stk = stackInfo(p);
      if (stk && stk.type === 'stack') {
        if (state.mode.indexOf('re_') === 0) score += 1;
        else { score += 3; reasons.push('Stacks w/ ' + stk.names[0]); }
      }
      // Cliff: big dropoff to the next available player at the position
      // Cliff must look at the WHOLE available pool, not the 30-player board
      // window (Jack, 2026-08-05 mock): Tucker Kraft was the last startable TE
      // inside the top 30, so `peers` held one entry, `nxt` came back
      // undefined, and the single biggest cliff on the board scored ZERO —
      // exactly when it mattered most. It also scales with the gap now: "next
      // TE is 30 VOR worse" is a different decision from "12 VOR worse".
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
        // Hard override, not a nudge: nothing else can legally be drafted.
        if (mustFill.indexOf(p.s) < 0) {
          score -= 100;
          rosterPen += 100;
          reasons.push('No spots left — must draft ' + mustFill.join(' + '));
        } else {
          score += 25;
          reasons.push('Required: ' + spotsLeft + ' pick' + (spotsLeft === 1 ? '' : 's') + ' for ' + mustFill.join(' + '));
        }
      } else if ((p.s === 'K' || p.s === 'DST') && rd < lateRd) { score -= 25; rosterPen += 25; }
      // Lineup redraft: you only START one QB / one TE — a backup there early
      // is a wasted pick. Huge penalty early, tapering late. Superflex raises
      // the QB starter count via slots_super_flex; dynasty modes skip this
      // (QB2/TE2 hold real trade value there).
      if (state.mode.indexOf('re_') === 0) {
        const qbStarters = (st.slots_qb || 0) + (st.slots_super_flex || 0) || 1;
        const teStarters = st.slots_te || 1;
        // The taper exists for teams that WAITED on the position — a
        // round-14 handcuff behind a round-11 QB is a normal build.
        const backupPenalty = rd <= 9 ? 40 : rd < lateRd ? 15 : 5;
        // ELITE QB/TE = POSITION CLOSED (Jack, 2026-08-06): in a redraft
        // league with waivers, owning a top guy at a one-starter position
        // ends it — you are DONE taking them, all draft long, so the taper
        // never applies. Your backup is the waiver wire. "Top" is measured
        // by WHERE HE GOES OFF THE BOARD, not the round you got him (Jack:
        // "2nd QB vs 9th QB") — Bowers falling to round 5 still closes TE,
        // a QB9 taken in round 6 doesn't close QB. qfill already scores what
        // you own by rank WITHIN the position (QB2 ≈ 0.85, QB5 ≈ 0.51, QB9 ≈
        // 0.26), so ≥ 0.5 ≈ top-5 positionally. Sole escape (Jack, same
        // session): the last couple rounds, and only for STEAL-grade value —
        // a faller 2+ rounds past his ADP in the final rounds is the one
        // time the dead pick isn't dead.
        const lastTwo = rd >= (st.rounds || 15) - 1;
        const closed = (pos) => {
          const q = qfill[pos] != null ? qfill[pos] : 0;
          return q >= 0.5 && !(lastTwo && adpTag(p) === 'STEAL');
        };
        // ABUNDANCE KILL (Jack, 2026-08-06): owning MORE QB/TE bodies than
        // the lineup starts is abundance whatever their rank — same flat 60
        // as elite-closed, never the taper (and the surplus multiplier below
        // stacks it). RB/WR depth stays useful, so only QB/TE run through
        // this block at all.
        const penaltyFor = (pos, have, starters) =>
          (closed(pos) || have > starters ? 60 : backupPenalty);
        // Scale by HOW MANY surplus bodies you'd own, not a flat hit (Jack,
        // 2026-08-05 mock: Burrow + Kyler already rostered in a 1QB league and
        // a third QB still surfaced at #2). Taking your QB2 costs 1x; your QB3
        // costs 2x, your QB4 3x — a third QB in a one-QB league is a dead
        // roster spot, not a mild inefficiency.
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
    // ---- leapfrog guard (Jack, 2026-08-03) ----
    // A lower-board player may only out-rank a higher-board player when the
    // timing play is real: the better player's ADP says he'll STILL be there
    // at your NEXT pick (so you take the one who won't last and bank the
    // better one) AND the two are ranked very close. Cross-position
    // leapfrogs take the same test, except a genuine position of NEED may
    // jump a position with abundant startable supply left. Otherwise the
    // better board player stays on top no matter what the bonuses say.
    const nextMine = myNextPickOverall();
    const idxOf = new Map();
    board.forEach((p, i) => idxOf.set(p, i));
    const leapfrogOk = (later, better) => {
      // A roster-nerfed player forfeits guard protection (Jack, 2026-08-06
      // ESPN mock: Bowers rostered in round 2, Loveland still recommended #1
      // — the −40 backup-TE penalty crushed his score, but he sat top of the
      // board, his ADP was inside Jack's next pick, and pre-round-5 the need
      // set is empty, so the guard clamped every OTHER player beneath him and
      // the penalty never mattered). The Underdog engine has carried this
      // exact exemption since v0.16.3; the port here never got it. The nerf
      // is the engine saying "not for THIS roster" — protecting him defeats
      // the nerf. Timing/ADP fades don't count toward rosterPen by design.
      if ((better.rosterPen || 0) >= 10) return true;
      const adp = better.p[modeKeys().adp];
      // Same decay: late on, ADP is no basis for letting a worse board player
      // jump a better one, so the guard stops accepting that argument.
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
      return needSet.has(later.p.s) && (supply[better.p.s] || 0) >= 8;
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
    // Locked with BOTH K and D/ST open: he's drafting one of each no matter
    // what, so the top recs should cover one of each — not three D/STs.
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

  // ---------- SEASON (regular) MODE ----------
  // The helper's second personality: instead of tracking a draft it tracks a
  // LEAGUE — optimal weekly lineup from the league's real roster slots +
  // real scoring_settings, and waiver targets ranked by how much they'd
  // actually improve YOUR starters (upgrade delta), not raw overall rank.
  // Everything comes from the same public API: /league/<id> (+ rosters,
  // users, matchups) and /state/nfl for the current week.
  const SEASON_POLL_MS = 60000;
  const INJ_TTL_MS = 12 * 3600 * 1000;
  const SLOT_ELIG = {
    QB: ['QB'], RB: ['RB'], WR: ['WR'], TE: ['TE'], K: ['K'], DEF: ['DST'],
    FLEX: ['RB', 'WR', 'TE'], SUPER_FLEX: ['QB', 'RB', 'WR', 'TE'],
    WRRB_FLEX: ['WR', 'RB'], REC_FLEX: ['WR', 'TE'],
    // IDP / unknown slots resolve to null → shown as unsupported
  };
  function lineupSlots() {
    const rp = (state.seasonLeague && state.seasonLeague.roster_positions) || [];
    return rp.filter((s) => s !== 'BN' && s !== 'IR' && s !== 'TAXI');
  }
  function myRosterDoc() {
    return state.seasonRosters.find((r) => r.roster_id === state.myLeagueRosterId) || null;
  }
  // Roster sleeper-ids → player objects. Ids we don't carry (deep stashes,
  // IDPs, just-drafted rookies) become stub entries named from the Sleeper
  // meta map so the lineup math never loses a body silently.
  function myPlayerObjs() {
    const r = myRosterDoc();
    if (!r) return [];
    return (r.players || []).map((pid) => {
      const sid = String(pid);
      const p = state.byId[sid];
      if (p) return p;
      const m = state.slMeta[sid];
      return { n: m ? m.n : '#' + sid, s: m ? m.pos : '?', sid, sTm: m ? m.tm : '', rank: 9999, _unmatched: true };
    });
  }
  function currentStarterIds() {
    const rid = state.myLeagueRosterId;
    const m = state.seasonMatchups.find((x) => x.roster_id === rid);
    const r = myRosterDoc();
    const arr = (m && Array.isArray(m.starters) && m.starters.length ? m.starters
      : (r && r.starters) || []);
    return arr.filter((x) => x && x !== '0').map(String);
  }
  // Week→opponent map from the site's Vegas lines (betting_lines_2026.json
  // gameTotals, keys W{wk}_{AWAY}_{HOME}). Also carries totals/spreads →
  // implied team totals for matchup coloring.
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
  // players.json carries no bye field, so byes are derived from the schedule:
  // a team with 8+ mapped weeks and no game this week is on bye.
  function onByeThisWeek(p) {
    if (!state.byesActive) return false;
    if (p.bye != null) return p.bye === state.seasonWeek;
    const sch = p.sTm && state.schedule[p.sTm];
    return !!(sch && Object.keys(sch).length >= 8 && !sch[state.seasonWeek]);
  }
  // This week's prop-board projection from the site's weeklyProps (UD + PP
  // blend, league-scored). Only trusted when a yardage line exists — a
  // TD-odds-only board is far too thin to project from. Receptions have no
  // book line, so estimate catches from receiving yards (RB ~7.5 ypr,
  // WR/TE ~11.5). Anytime-TD American odds → expected TDs. Cached per
  // player per week+scoring.
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
        const sv = state.scoringVals || { recPts: 1, passTd: 4, teBonus: 0 };
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
          pts += recEst * ((sv.recPts != null ? sv.recPts : 1) + (p.s === 'TE' && sv.teBonus ? sv.teBonus : 0));
        }
        const atd = avg('atd');
        if (atd != null) {
          const prob = atd < 0 ? -atd / (-atd + 100) : 100 / (atd + 100);
          pts += prob * (p.s === 'QB' ? 1 : 1.1) * 6; // QB atd = rush TD only
        }
        out = Math.round(pts * 10) / 10;
      }
    }
    p._wkpKey = cacheKey;
    p._wkpVal = out;
    return out;
  }
  // Matchup info for the current week, colored by Vegas implied total
  // (for DST: the OPPONENT's implied — lower is better). Shared by the
  // sidebar pill and the on-page team decorator.
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
    const col = good ? ['#2a4030', '#6dd06d'] : bad ? ['#402a2a', '#d06d6d'] : ['#26304d', '#cbd2e6'];
    const txt = (g.home ? 'vs' : '@') + g.opp;
    return {
      txt, bg: col[0], fg: col[1], cls: good ? 'good' : bad ? 'bad' : 'mid',
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
  // Shared lineup verdicts: optimal lineup + start/sit moves + per-player
  // verdict ('go' start him / 'sit' bench him / 'close' toss-up). Used by
  // the LINEUP tab and the on-page team decorator.
  const CLOSE_PPG = 1.5;
  function seasonLineupCalc() {
    if (!myRosterDoc()) return null;
    const pool = myPlayerObjs();
    const opt = optimalLineup(pool);
    const starterSet = new Set(currentStarterIds());
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
  // ---- modeled K/DST projections (league-scored, Vegas-driven) ----
  // Kicker: Clay's per-kicker FG/XP season volumes, scaled by the week's
  // implied total (FG volume moves mildly with team scoring; XP volume
  // tracks TDs ~linearly), scored with the league's REAL kicker rules.
  // Distance mix per kicker from ESPN actuals (kD — Aubrey takes ~3x the
  // 50+ shots Moody does, which cashes in distance-bonus leagues);
  // league-average mix when unknown.
  const FG_MIX_AVG = [0.02, 0.22, 0.30, 0.30, 0.16];
  const FG_KEYS = ['fgm_0_19', 'fgm_20_29', 'fgm_30_39', 'fgm_40_49', 'fgm_50p'];
  const FG_DEF_PTS = [3, 3, 3, 4, 5];
  function kickerProjFor(p, g) {
    const T = g && g.implied != null ? g.implied : 22.5;
    if (p.kFga == null) return 5 + (T - 22.5) * 0.3; // backup K — flat, Vegas-nudged
    const gm = p.cGm || 17;
    const fgScale = (0.036 * T + 0.74) / 1.55;            // ≈1.0 at a 22.5 implied
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
  // DST: expected stat line vs the OPPONENT's implied total (sacks and
  // turnovers fall as it rises), quality-scaled by Clay's defense rank,
  // plus the league's points-allowed brackets integrated over a logistic
  // distribution centered on the opponent implied. League-scored throughout.
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
    const q = p.dRk != null ? 1 + (16.5 - p.dRk) * 0.012 : 1; // rank 1 → ×1.19
    const sacks = Math.max(0.5, 3.6 - 0.055 * O) * q;
    const ints = Math.max(0.2, 1.5 - 0.025 * O) * q;
    const dtd = Math.max(0.05, 0.28 - 0.005 * O) * q;
    let pts = sacks * val('sack', 1) + ints * val('int', 2) + 0.5 * q * val('fum_rec', 2) +
      dtd * val('def_td', 6) + 0.06 * q * val('safe', 2) + 0.07 * q * val('blk_kick', 2);
    if (sc.ff) pts += 0.85 * q * sc.ff;
    const cdf = (x) => 1 / (1 + Math.exp(-(x - O) / 5.6)); // ~normal σ≈9.5
    for (let i = 0; i < PA_BUCKETS.length; i++) {
      const b = PA_BUCKETS[i];
      pts += (cdf(b[2]) - cdf(b[1])) * val(b[0], b[3]);
    }
    return pts;
  }
  // This-week value: site W1+ prop-board projection blended 80/20 with the
  // league-scored Clay PPG when a board exists (Clay-only otherwise), zeroed
  // on bye (regular season only) and for OUT/IR players, discounted for
  // Doubtful/Questionable, then nudged by Jack's redraft rank (±1.5 ppg).
  // K/DST: fully modeled above from league rules + Vegas; no rank nudge
  // (their projections already encode quality).
  // ---- engine-mean weekly projection (the sim engine's number, no RNG) ----
  // Same mean the PICKS-tab season sim draws around: Clay rescored to the
  // league's real scoring × Vegas implied-total multiplier (backtested
  // per-position elasticity) × defense adjustment, QB/injury windows + rookie
  // ramps applied. jsMean flavor: once the bundled pack carries 2026 actuals
  // it auto-shrinks Clay toward them (preseason it equals the plain mean).
  // Cached per week+scoring. K/DST excluded — the sidebar's own league-scored
  // Vegas models below are sharper than the engine's flat DST formula.
  let _engWk = null;
  function engineWeekMap() {
    if (!simAvailable() || !state.seasonLeague || !state.seasonLeague.scoring_settings) return null;
    const key = state.seasonWeek + '|' + state.scoringLabel;
    if (_engWk && _engWk.key === key) return _engWk;
    const E = window.SimEngine;
    const bySid = {}, byNorm = {};
    try {
      const sched = pkSchedule();
      if (!sched || !Object.keys(sched.byTeam).length) return null;
      pkEnsureGlobals();
      const players = E.buildPlayers(sched);
      const sc = E.scoringFromLeague(state.seasonLeague.scoring_settings);
      players.list.forEach((ep) => {
        if (ep.isDST || ep.pos === 'K') return;
        const wp = E.weeklyProjection(ep, state.seasonWeek, sc, sched);
        const m = wp && (wp.jsMean != null ? wp.jsMean : wp.mean);
        if (!(m > 0)) return;
        const rec = { m, sig: ep.sigmaPct, pos: ep.pos };
        if (ep.sid) bySid[ep.sid] = rec;
        if (byNorm[ep.norm] === undefined) byNorm[ep.norm] = rec;
      });
    } catch (e) { console.warn('MFF engineWeekMap failed:', e); return null; }
    _engWk = { key, bySid, byNorm };
    return _engWk;
  }
  function engineRecFor(p) {
    const m = engineWeekMap();
    if (!m) return null;
    let r = p.sid != null ? m.bySid[String(p.sid)] : undefined;
    if (r === undefined) r = m.byNorm[window.SimEngine.norm(p.n)];
    return r || null;
  }
  function engineMeanFor(p) {
    const r = engineRecFor(p);
    return r ? r.m : null;
  }
  // Boom/bust odds, analytic. The engine's marginal weekly distribution is
  // gamma(mean, sd = mean × sigmaPct) — the correlation structure preserves
  // marginals exactly — so P(boom)/P(bust) come from the regularized
  // incomplete gamma (series + continued fraction), no sampling needed.
  // Evaluated at the DISPLAYED proj (post injury-discount/nudge) so the odds
  // always describe the number next to them.
  function lnGamma(z) {
    const g = [76.18009172947146, -86.50532032941677, 24.01409824083091,
      -1.231739572450155, 0.1208650973866179e-2, -0.5395239384953e-5];
    let y = z, tmp = z + 5.5, ser = 1.000000000190015;
    tmp -= (z + 0.5) * Math.log(tmp);
    for (let j = 0; j < 6; j++) ser += g[j] / ++y;
    return -tmp + Math.log(2.5066282746310005 * ser / z);
  }
  function gammP(a, x) {
    if (x <= 0) return 0;
    if (x < a + 1) {
      let ap = a, sum = 1 / a, del = sum;
      for (let i = 0; i < 300; i++) {
        ap += 1; del *= x / ap; sum += del;
        if (Math.abs(del) < Math.abs(sum) * 1e-9) break;
      }
      return sum * Math.exp(-x + a * Math.log(x) - lnGamma(a));
    }
    let b = x + 1 - a, c = 1e300, d = 1 / b, h = d;
    for (let i = 1; i < 300; i++) {
      const an = -i * (i - a);
      b += 2; d = an * d + b; if (Math.abs(d) < 1e-300) d = 1e-300;
      c = b + an / c; if (Math.abs(c) < 1e-300) c = 1e-300;
      d = 1 / d; const del = d * c; h *= del;
      if (Math.abs(del - 1) < 1e-9) break;
    }
    return 1 - Math.exp(-x + a * Math.log(x) - lnGamma(a)) * h;
  }
  function boomBustFor(p, mean) {
    const r = engineRecFor(p);
    const E = window.SimEngine;
    const bb = E && E.BOOM_BUST && E.BOOM_BUST[p.s];
    if (!r || !bb || !(mean > 0) || !(r.sig > 0)) return null;
    const k = 1 / (r.sig * r.sig), th = mean * r.sig * r.sig;
    return { boom: 1 - gammP(k, bb.boom / th), bust: gammP(k, bb.bust / th), boomAt: bb.boom, bustAt: bb.bust };
  }
  function bbTip(bb) {
    return 'From the sim distribution: ' + Math.round(bb.boom * 100) + '% boom (≥' + bb.boomAt +
      ' pts) · ' + Math.round(bb.bust * 100) + '% bust (<' + bb.bustAt + ' pts)';
  }
  function bbTagHTML(p, v) {
    const bb = boomBustFor(p, v);
    if (!bb) return '';
    return `<span class="tag" style="background:#26304d" title="${esc(bbTip(bb))}">` +
      `<span style="color:#6dd06d">▲${Math.round(bb.boom * 100)}</span> ` +
      `<span style="color:#d06d6d">▼${Math.round(bb.bust * 100)}</span></span>`;
  }
  function bbPillHTML(bb) {
    return `<span title="${esc(bbTip(bb))}" style="background:#26304d;font-size:10px;font-weight:700;` +
      'border-radius:3px;padding:0 4px;line-height:15px;white-space:nowrap;flex:0 0 auto">' +
      `<span style="color:#6dd06d">▲${Math.round(bb.boom * 100)}</span>&nbsp;` +
      `<span style="color:#d06d6d">▼${Math.round(bb.bust * 100)}</span></span>`;
  }
  function wkVal(p) {
    if (onByeThisWeek(p)) return 0;
    const act = actualPpgFor(p);
    const shrink = act ? act.gp / (act.gp + PRIOR_GAMES) : 0;
    let v;
    if (p.s === 'K' || p.s === 'DST') {
      const g = p.sTm && state.schedule[p.sTm] && state.schedule[p.sTm][state.seasonWeek];
      v = p.s === 'K' ? kickerProjFor(p, g) : dstProjFor(p, g);
      // Decay toward actuals as an additive correction so the matchup logic
      // survives: (actual season ppg − preseason expectation) × shrink.
      // Both sides of each diff share a scoring basis (K: flat Clay ppg;
      // DST: the league-scored model at a neutral 22.5 implied).
      if (act) {
        const prior = p.s === 'K' ? (p.pPg != null ? p.pPg : 7.5) : dstProjFor(p, null);
        v += (act.ppg - prior) * shrink;
      }
      v = Math.max(1, v);
    } else {
      // SIM-FIRST: the site's Sim Lab weekly row (full engine — correlations,
      // in-season actuals blend, injury zeros/redistribution, frozen at
      // kickoff) is the number wherever it exists; the local engine port,
      // then props/Clay blend, remain the fallbacks.
      let _fromSim = false;
      const _six = simProjIdx();
      const _wkMap = _six && (_six.weeks[state.seasonWeek] || _six.weeks[state.simProj.currentWeek]);
      const _sr = _wkMap && _wkMap[simKeyFor(p)];
      if (_sr && typeof _sr[1] === 'number') {
        if (_sr[1] === 0 && _sr[3] == null) return 0; // ruled out at export time
        v = _sr[1] + simLeagueDeltaPg(p);
        _fromSim = true;
      } else {
        const em = engineMeanFor(p);
        if (em != null) {
          v = em;
        } else {
          let base = p.pPg != null ? p.pPg : 0;
          if (act) base += (act.ppg - base) * shrink; // preseason proj decays per game played
          v = base;
          const props = propsProjFor(p);
          if (props != null) v = (p.pPg != null || act) ? 0.8 * props + 0.2 * base : props;
        }
      }
      // Sim rows already price designations as of the last site export run
      // (daily + pre-kickoff) — don't re-discount D/Q on top; OUT (fresher
      // live status) still zeroes below.
      if (_fromSim) {
        const _m = p.sid && state.slMeta[p.sid];
        if (_m && _m.inj === 'OUT') return 0;
        if (v > 0 && p.rank != null && !p._unmatched) {
          v += Math.max(-0.67, Math.min(1, (100 - p.rank) / 100)) * 1.5;
          if (v < 0) v = 0;
        }
        return Math.round(v * 100) / 100;
      }
    }
    const m = p.sid && state.slMeta[p.sid];
    if (m && m.inj) {
      if (m.inj === 'OUT') return 0;
      if (m.inj === 'D') v *= 0.3;
      else if (m.inj === 'Q') v *= 0.85;
    }
    if (v > 0 && p.rank != null && !p._unmatched && p.s !== 'K' && p.s !== 'DST') {
      v += Math.max(-0.67, Math.min(1, (100 - p.rank) / 100)) * 1.5;
      if (v < 0) v = 0;
    }
    return Math.round(v * 100) / 100;
  }
  // Greedy optimal lineup over the league's real slots: dedicated positions
  // fill first, then narrow flexes (WR/RB, WR/TE), then FLEX, then SUPER_FLEX
  // — same approach as the draft-side starterProjPPG.
  function optimalLineup(pool) {
    const slots = lineupSlots();
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
  // Start/sit moves: optimal players not currently starting, paired with the
  // weakest current starters who dropped out of the optimal lineup.
  function lineupMoves(opt, starterSet, pool) {
    const adds = opt.assign
      .filter((a) => a.e && a.e.p.sid && !starterSet.has(a.e.p.sid))
      .map((a) => a.e)
      .sort((a, b) => b.v - a.v);
    const optIds = new Set(opt.assign.filter((a) => a.e && a.e.p.sid).map((a) => a.e.p.sid));
    const sits = pool.filter((p) => p.sid && starterSet.has(p.sid) && !optIds.has(p.sid))
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
  // ---- waivers ----
  function freeAgents() {
    const rostered = new Set();
    for (const r of state.seasonRosters) {
      for (const pid of (r.players || [])) rostered.add(String(pid));
    }
    return state.players.filter((p) => p.sid && !rostered.has(String(p.sid)));
  }
  // The "you have Josh Allen" rule: every free agent is scored by the ppg he
  // adds to YOUR optimal lineup (upgrade delta). A top-10 QB behind a rostered
  // stud scores ~0 lineup delta and sinks to depth; a mid WR who beats your
  // WR3 jumps the queue. ROS quality (league-scored pPg), Sleeper 24h add
  // trends, and (dynasty) KTC break the ties.
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
      const trend = state.trendAdds[p.sid] || 0;
      let score = delta * 4 + (p.pPg || 0) * 0.6;
      if (dyn && p[mk.ktc] != null) score += p[mk.ktc] / 400;
      if (trend) score += Math.min(3, Math.log10(trend + 1) * 1.5);
      return { p, delta, trend, score: Math.round(score * 10) / 10 };
    });
    scored.sort((a, b) => b.score - a.score);
    return scored.slice(0, 25);
  }
  // Keep-score per rostered player: marginal lineup contribution (what the
  // starters lose if he vanishes) + ROS value (+ KTC in dynasty). Lowest keep
  // = the drop candidate.
  function dropCandidates() {
    const mine = myPlayerObjs();
    const base = optimalLineup(mine).total;
    const dyn = state.mode.indexOf('dyn') === 0;
    const mk = modeKeys();
    // A position the lineup REQUIRES with only one rostered body is protected
    // — never suggest dropping your only K/DST/QB into an empty slot.
    const slots = lineupSlots();
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
  // ---- league loading ----
  async function refreshLeagueData() {
    const lid = state.seasonLeagueId;
    if (!lid) return;
    const [users, rosters, matchups] = await Promise.all([
      api('/league/' + lid + '/users').catch(() => []),
      api('/league/' + lid + '/rosters').catch(() => []),
      api('/league/' + lid + '/matchups/' + state.seasonWeek).catch(() => []),
    ]);
    if (Array.isArray(users)) {
      for (const u of users) state.userNames[u.user_id] = u.display_name || u.username;
    }
    state.seasonRosters = Array.isArray(rosters) ? rosters : [];
    state.seasonMatchups = Array.isArray(matchups) ? matchups : [];
    state.seasonStatus = state.seasonRosters.length + ' teams · week ' + state.seasonWeek +
      (state.byesActive ? '' : ' (preseason)');
  }
  async function ensureNflState() {
    if (state.nflState) return;
    try {
      const nfl = await api('/state/nfl');
      state.nflState = nfl || {};
      const wk = nfl && nfl.season_type === 'regular' ? nfl.week : null;
      state.seasonWeek = wk && wk >= 1 ? wk : 1;
      state.byesActive = !!(nfl && nfl.season_type === 'regular');
    } catch (e) { state.nflState = {}; }
  }
  async function findSeasonTeam() {
    if (!state.username) return false;
    try {
      if (!state.myUserId) {
        const user = await api('/user/' + encodeURIComponent(state.username));
        if (user && user.user_id) state.myUserId = user.user_id;
      }
      const r = state.seasonRosters.find((x) => x.owner_id === state.myUserId ||
        (Array.isArray(x.co_owners) && x.co_owners.indexOf(state.myUserId) !== -1));
      if (r) {
        state.myLeagueRosterId = r.roster_id;
        saveSeasonPrefs();
        return true;
      }
    } catch (e) {}
    return false;
  }
  async function loadMyLeagues() {
    if (!state.username) {
      state.seasonStatus = 'Set your Sleeper username to list your leagues';
      render();
      return;
    }
    try {
      await ensureNflState();
      if (!state.myUserId) {
        const user = await api('/user/' + encodeURIComponent(state.username));
        if (user && user.user_id) state.myUserId = user.user_id;
      }
      const season = (state.nflState && (state.nflState.league_season || state.nflState.season)) || '2026';
      const ls = await api('/user/' + state.myUserId + '/leagues/nfl/' + season);
      state.myLeagues = Array.isArray(ls) ? ls : [];
      state.seasonStatus = state.myLeagues.length + ' league' + (state.myLeagues.length === 1 ? '' : 's') + ' found';
    } catch (e) {
      state.seasonStatus = 'League lookup failed: ' + e.message;
    }
    render();
  }
  // Sleeper's full player dump (~5MB) → trimmed {sid: {n,pos,tm,inj}} map for
  // injury flags + names for roster ids outside our 580-player export.
  // Cached 12h in extension storage; fantasy positions only.
  async function fetchInjuries() {
    try {
      const saved = await store.get(['sleeperHelper.slMeta4']);
      const cached = saved['sleeperHelper.slMeta4'];
      if (cached && cached.ts && Date.now() - cached.ts < INJ_TTL_MS) {
        state.slMeta = cached.map || {};
        render(); // both modes show injury chips now
        return;
      }
    } catch (e) {}
    try {
      const all = await api('/players/nfl');
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
        // Raw designations + experience for the season-sim engine (PICKS tab):
        // exp 0 = TRUE rookie (drives sigma widening + ramps); is/st feed
        // injury start-of-season windows and the IR/PUP roster exclusion.
        if (typeof pl.years_exp === 'number') entry.exp = pl.years_exp;
        if (pl.injury_status) entry.is = pl.injury_status;
        if (pl.status && pl.status !== 'Active') entry.st = pl.status;
        // Detail fields for the injury popover (2026-08-27): body part, start
        // date, note — same Sleeper dump, so no extra request.
        if (pl.injury_body_part) entry.ib = pl.injury_body_part;
        if (pl.injury_start_date) entry.idt = pl.injury_start_date;
        if (pl.injury_notes) entry.inx = String(pl.injury_notes).slice(0, 200);
        map[sid] = entry;
      }
      state.slMeta = map;
      store.set({ 'sleeperHelper.slMeta4': { ts: Date.now(), map } });
      render(); // both modes show injury chips now
    } catch (e) { /* flags just stay off */ }
  }
  // ---- in-season decay of preseason projections ----
  // After every played week, pull that week's actual fantasy points from
  // Sleeper's public stats endpoint and aggregate a season-to-date PPG per
  // player. wkVal then shrinks the preseason base toward the actuals with
  // the prior worth ~6 games (3 gm → 33% actuals, 10 gm → 63%). Preseason:
  // nothing played → projections stand unchanged.
  const PRIOR_GAMES = 6;
  async function fetchSeasonStats() {
    if (!state.byesActive || state.seasonWeek <= 1) return; // no games played yet
    const upTo = state.seasonWeek - 1;
    const season = (state.nflState && state.nflState.season) || '2026';
    try {
      const saved = await store.get(['sleeperHelper.seasonStats']);
      const c = saved['sleeperHelper.seasonStats'];
      if (c && c.season === season && c.upToWk === upTo && Date.now() - c.ts < 6 * 3600 * 1000) {
        state.seasonStats = c;
        if (state.appMode === 'season') render();
        return;
      }
    } catch (e) {}
    try {
      const byId = {};
      for (let wk = 1; wk <= upTo; wk++) {
        const stats = await api('/stats/nfl/regular/' + season + '/' + wk);
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
      store.set({ 'sleeperHelper.seasonStats': state.seasonStats });
      if (state.appMode === 'season') render();
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
    try {
      const t = await api('/players/nfl/trending/add?lookback_hours=24&limit=50');
      state.trendAdds = {};
      if (Array.isArray(t)) for (const x of t) state.trendAdds[String(x.player_id)] = x.count;
    } catch (e) {}
  }

  // ---------- PICKS tab: sim-driven future-pick values (v0.14.0) ----------
  // Port of Sim Lab's team-aware pick valuation: run the season-sim engine
  // (engine_sim.js — verbatim sim_lab copy, fed by data/sim_pack.js) over this
  // league, keep each team's FULL finish distribution, and value 2027/2028
  // picks off the ORIGINAL team's distribution — draft order = inverse
  // standings, EV integrated over a slot-value curve through the KTC
  // Early/Mid/Late anchors. A rebuilder's 1st prices above a contender's 1st,
  // and collapse-tail risk earns extra credit (early slots are convex).
  const PK_SIMS = 1500, PK_SEED = 99;
  const PK_ROUNDS = ['1st', '2nd', '3rd', '4th'];
  const PK_YEARS = [2027, 2028, 2029]; // 2029 has no KTC anchors (valued ~extrapolated) but its true ownership must be tracked
  state.pickSim = { leagueId: null, status: 'idle', placeCounts: null, results: null, sims: PK_SIMS,
    inv: null, tradedCount: 0, recHash: null, synthPairs: false, note: '', selTeam: null };
  function simAvailable() {
    return !!(window.SimEngine && typeof MIKE_CLAY_PROJ !== 'undefined' &&
      typeof PLAYER_WEEKLY_SIGMA !== 'undefined');
  }
  function pkDynasty() { // Sleeper settings.type: 0 redraft, 1 keeper, 2 dynasty
    const lg = state.seasonLeague;
    return !!(lg && lg.settings && lg.settings.type >= 1);
  }
  function pkTabVisible() {
    return simAvailable() && !!state.seasonLeague; // standings/odds for every league type; pick sections are dynasty/keeper only
  }
  let _pkSchedule = null;
  function pkSchedule() {
    if (!_pkSchedule && window.BETTING_2026) _pkSchedule = window.SimEngine.buildSchedule();
    return _pkSchedule;
  }
  function pkEnsureGlobals() {
    // The engine matches Clay names → Sleeper ids/age/KTC through SIM_SLEEPER,
    // and rookie/injury designations through SIM_SLEEPER_META.
    if (!window.SIM_SLEEPER) {
      window.SIM_SLEEPER = { players: state.players.filter((p) => p.sid && p.s !== 'PICK').map((p) => ({
        n: p.n, sid: p.sid, a: p.a, age: p.age, ktc1qb: p.ktc1qb, ktcSf: p.ktcSf })) };
    }
    const meta = {};
    for (const sid of Object.keys(state.slMeta)) {
      const e = state.slMeta[sid];
      if (e.exp != null || e.is || e.st) meta[sid] = { exp: e.exp, inj: e.is || '', st: e.st || '' };
    }
    window.SIM_SLEEPER_META = meta;
  }
  const PK_IR_STATUS = /^(Injured Reserve|Physically Unable|Non Football|Suspended|Reserve)/i;
  function pkUnavailable() {
    // Mirror sim_lab rules: hard-out roster statuses gone all season; weekly
    // "Out" benches the current week only (regular season); PUP counts only
    // in-season (camp PUP players are usually active by W1); Q/D untouched —
    // the sim's variance owns those.
    const out = {};
    for (const sid of Object.keys(state.slMeta)) {
      const e = state.slMeta[sid];
      const st = e.st || '', is = e.is || '';
      if (PK_IR_STATUS.test(st) || /^(IR|NA|COV|DNR)/i.test(is) ||
          (state.byesActive && /^(PUP|Sus)/i.test(is))) out[sid] = 'ir';
      else if (state.byesActive && /^Out/i.test(is)) out[sid] = 'out';
    }
    return out;
  }
  function pkTeams() {
    return state.seasonRosters.map((r) => {
      const benched = {}; // league-enforced IR/taxi slots can't start
      (r.reserve || []).concat(r.taxi || []).forEach((id) => { benched[String(id)] = 1; });
      const s = r.settings || {};
      return {
        rosterId: r.roster_id,
        name: state.userNames[r.owner_id] || 'Team ' + r.roster_id,
        playerIds: (r.players || []).map(String).filter((id) => !benched[id]),
        record: (state.byesActive && (s.wins || s.losses)) ? {
          w: s.wins || 0, l: s.losses || 0,
          pf: (s.fpts || 0) + (s.fpts_decimal || 0) / 100 } : null,
      };
    });
  }
  function pkRecHash() {
    return state.seasonRosters.map((r) => {
      const s = r.settings || {};
      return r.roster_id + ':' + (s.wins || 0) + '-' + (s.losses || 0);
    }).join('|');
  }
  function pkRoundRobin(ids, weeks) {
    // Offseason fallback until Sleeper publishes matchups (same as sim_lab).
    const arr = ids.slice();
    if (arr.length % 2) arr.push(null);
    const n = arr.length, half = n / 2, pairsByWeek = {};
    weeks.forEach((wk) => {
      const pairs = [];
      for (let j = 0; j < half; j++) {
        const a = arr[j], b = arr[n - 1 - j];
        if (a != null && b != null) pairs.push({ a, b });
      }
      pairsByWeek[wk] = pairs;
      arr.splice(1, 0, arr.pop()); // rotate all but first
    });
    return pairsByWeek;
  }
  async function pkFetchPairs(lid, regWeeks) {
    const key = 'sleeperPairs_' + lid;
    const day = new Date().toDateString();
    try {
      const saved = await store.get([key]);
      const c = saved[key];
      if (c && c.day === day && c.weeks === regWeeks.join(',')) return c;
    } catch (e) {}
    const results = await Promise.all(regWeeks.map((wk) =>
      api('/league/' + lid + '/matchups/' + wk).catch(() => [])));
    const pairsByWeek = {};
    let anyPairs = false;
    regWeeks.forEach((wk, i) => {
      const byM = {};
      (Array.isArray(results[i]) ? results[i] : []).forEach((m) => {
        if (m && m.matchup_id != null) (byM[m.matchup_id] = byM[m.matchup_id] || []).push(m.roster_id);
      });
      const lst = [];
      Object.keys(byM).forEach((mid) => { if (byM[mid].length === 2) lst.push({ a: byM[mid][0], b: byM[mid][1] }); });
      if (lst.length) { pairsByWeek[wk] = lst; anyPairs = true; }
    });
    const rec = { day, weeks: regWeeks.join(','), pairsByWeek, anyPairs };
    store.set({ [key]: rec });
    return rec;
  }
  async function pkFetchInventory(lid) {
    // Everyone starts with their own 2027/2028 rd 1-4 picks; Sleeper's
    // traded_picks record moves them (orig team stays attached — it drives
    // the pick's value via that team's projected finish).
    const inv = {};
    state.seasonRosters.forEach((r) => { inv[r.roster_id] = []; });
    PK_YEARS.forEach((y) => {
      for (let rd = 1; rd <= 4; rd++) {
        state.seasonRosters.forEach((r) => inv[r.roster_id].push({ year: y, round: rd, orig: r.roster_id }));
      }
    });
    let traded = [];
    try { traded = await api('/league/' + lid + '/traded_picks'); } catch (e) {}
    let moved = 0;
    (Array.isArray(traded) ? traded : []).forEach((tp) => {
      const y = +tp.season, rd = tp.round, orig = tp.roster_id, owner = tp.owner_id;
      if (PK_YEARS.indexOf(y) === -1 || rd > 4 || orig == null || owner == null || orig === owner) return;
      const from = inv[orig] || [];
      const idx = from.findIndex((p) => p.year === y && p.round === rd && p.orig === orig);
      if (idx >= 0) from.splice(idx, 1);
      if (inv[owner]) { inv[owner].push({ year: y, round: rd, orig }); moved++; }
    });
    return { inv, moved };
  }
  // Assemble every simLeague input for this league (cached per league+records).
  // Shared by ensurePickSim and the trade-impact before/after runs.
  async function pkSimInputs() {
    const lid = state.seasonLeagueId;
    const recHash = pkRecHash();
    if (state._pkInputs && state._pkInputs.lid === lid && state._pkInputs.recHash === recHash) {
      return state._pkInputs;
    }
    const E2 = window.SimEngine;
    const sched = pkSchedule();
    if (!sched || !Object.keys(sched.byTeam).length) throw new Error('no Vegas lines loaded');
    const lg = state.seasonLeague || {};
    const lset = lg.settings || {};
    const playoffStart = lset.playoff_week_start || 15;
    const playoffTeams = lset.playoff_teams || 6;
    const curWeek = state.byesActive ? state.seasonWeek : 1;
    const regWeeks = [];
    for (let w = curWeek; w < playoffStart; w++) regWeeks.push(w);
    const teams = pkTeams();
    const pr = await pkFetchPairs(lid, regWeeks);
    const pairsByWeek = pr.anyPairs ? pr.pairsByWeek
      : pkRoundRobin(teams.map((t) => t.rosterId), regWeeks);
    pkEnsureGlobals();
    const players = E2.buildPlayers(sched);
    const slots = (lg.roster_positions || []).filter((s) => s !== 'BN' && s !== 'IR' && s !== 'TAXI');
    state._pkInputs = { lid, recHash, sched, teams, pairsByWeek, regWeeks, playoffStart, playoffTeams,
      slots, scoring: E2.scoringFromLeague(lg.scoring_settings), unavailable: pkUnavailable(),
      curWeek, players, synthPairs: !pr.anyPairs };
    return state._pkInputs;
  }
  function pkRunSim(inp, teams) {
    return window.SimEngine.simLeague({
      teams, sims: PK_SIMS, seed: PK_SEED, scoring: inp.scoring,
      schedule: inp.sched, players: inp.players, pairsByWeek: inp.pairsByWeek, regWeeks: inp.regWeeks,
      playoffTeams: inp.playoffTeams, playoffStart: inp.playoffStart, lineupSlots: inp.slots,
      unavailable: inp.unavailable, currentWeek: inp.curWeek,
    });
  }
  async function ensurePickSim() {
    const lid = state.seasonLeagueId;
    const ps = state.pickSim;
    if (!lid || !simAvailable() || !state.seasonRosters.length) return;
    if (ps.leagueId === lid &&
      (ps.status === 'running' || (ps.status === 'done' && ps.recHash === pkRecHash()))) return;
    ps.leagueId = lid; ps.status = 'running'; ps.note = '';
    render();
    await new Promise((r) => setTimeout(r, 30)); // let the status paint before the sync sim
    try {
      const invRes = await pkFetchInventory(lid); // always fresh — trades move picks
      ps.inv = invRes.inv; ps.tradedCount = invRes.moved;
      const recHash = pkRecHash();
      const day = new Date().toDateString();
      const cacheKey = 'sleeperPickSim_' + lid;
      try { // day+records-keyed cache: finish distributions barely move intraday
        const saved = await store.get([cacheKey]);
        const c = saved[cacheKey];
        if (c && c.v === 2 && c.day === day && c.recHash === recHash && c.placeCounts) {
          Object.assign(ps, { status: 'done', placeCounts: c.placeCounts, results: c.results,
            sims: c.sims || PK_SIMS, recHash, synthPairs: !!c.synthPairs });
          render();
          return;
        }
      } catch (e) {}
      const inp = await pkSimInputs();
      const teams = inp.teams;
      const regWeeks = inp.regWeeks;
      ps.synthPairs = inp.synthPairs;
      const res = pkRunSim(inp, teams);
      const placeCounts = {}, results = {};
      res.forEach((r) => {
        placeCounts[r.team.rosterId] = r.placeCounts;
        // trimmed per-team summary for the standings table + weekly drill-down
        const carried = r.team.record ? (r.team.record.w || 0) + (r.team.record.l || 0) : 0;
        const games = carried + regWeeks.length;
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
      Object.assign(ps, { status: 'done', placeCounts, results, sims: PK_SIMS, recHash });
      store.set({ [cacheKey]: { v: 2, day, recHash, placeCounts, results, sims: PK_SIMS, synthPairs: ps.synthPairs } });
    } catch (e) {
      ps.status = 'error';
      ps.note = e.message || String(e);
    }
    render();
  }
  // ---- valuation (verbatim math from sim_lab app.js teamPickValue) ----
  function pkSf() {
    const rp = (state.seasonLeague && state.seasonLeague.roster_positions) || [];
    return rp.indexOf('SUPER_FLEX') !== -1;
  }
  function pkAnchors(year, roundKey, sf) {
    const v = (tier) => {
      const pk = state.pickAssets.find((p) => p.n === year + ' ' + tier + ' ' + roundKey);
      return pk ? ((sf ? pk.ktcSf : pk.ktc1qb) || null) : null;
    };
    const e = v('Early'), m = v('Mid'), l = v('Late');
    return (e != null && m != null && l != null) ? { e, m, l } : null;
  }
  function pkSlotValue(slot, a, n) {
    const s1 = n * 2.5 / 12, s2 = n * 6.5 / 12, s3 = n * 10.5 / 12; // anchor slots scaled to league size
    if (slot <= s1) return a.e;
    if (slot >= s3) return a.l;
    if (slot <= s2) return a.e + (a.m - a.e) * (slot - s1) / (s2 - s1);
    return a.m + (a.l - a.m) * (slot - s2) / (s3 - s2);
  }
  function pkTeamPickValue(rid, year, roundKey) {
    const a = pkAnchors(year, roundKey, pkSf());
    if (!a) return null;
    const n = state.seasonRosters.length || 12;
    const ps = state.pickSim;
    const f = ps.status === 'done' && ps.placeCounts ? ps.placeCounts[rid] : null;
    if (!f) return Math.round((a.e + a.m + a.l) / 3); // no sim → generic tier avg
    const blend = year >= 2028 ? 0.5 : 0; // two years of roster churn → regress
    let ev = 0, tot = 0;
    for (let place = 1; place <= n; place++) {
      let p = (f[place] || 0) / ps.sims;
      p = (1 - blend) * p + blend / n;
      ev += p * pkSlotValue(n + 1 - place, a, n);
      tot += p;
    }
    return Math.round(ev / (tot || 1));
  }
  function pkExpFinish(rid) {
    const ps = state.pickSim;
    const f = ps.status === 'done' && ps.placeCounts ? ps.placeCounts[rid] : null;
    if (!f) return null;
    const n = state.seasonRosters.length || 12;
    let ev = 0, mode = 1, modeP = 0;
    for (let pl = 1; pl <= n; pl++) {
      const p = (f[pl] || 0) / ps.sims;
      ev += pl * p;
      if (p > modeP) { modeP = p; mode = pl; }
    }
    return { ev, mode, modeP };
  }
  function pkOwnerOf(year, round, orig) {
    const inv = state.pickSim.inv || {};
    for (const rid of Object.keys(inv)) {
      if (inv[rid].some((p) => p.year === year && p.round === round && p.orig === orig)) return +rid;
    }
    return null;
  }
  function pkOrdinal(v) {
    const s = ['th', 'st', 'nd', 'rd'], t = v % 100;
    return v + (s[(t - 20) % 10] || s[t] || s[0]);
  }
  function saveSeasonPrefs() {
    if (!state.seasonLeagueId) return;
    store.set({
      ['sleeperSeason_' + state.seasonLeagueId]: {
        rosterId: state.myLeagueRosterId,
        tab: state.seasonTab,
        posFilter: state.seasonPosFilter,
        teamSrc: state.seasonTeamSrc,
      },
      'sleeperHelper.lastLeague': state.seasonLeagueId,
    });
  }
  async function initForLeague(leagueId) {
    state.seasonLeagueId = leagueId;
    state.seasonLeague = null;
    state.seasonRosters = [];
    state.seasonMatchups = [];
    state.myLeagueRosterId = null;
    state.seasonStatus = 'Loading league…';
    stopSeasonPolling();
    buildPanel();
    render();
    try {
      const saved = await store.get(['sleeperSeason_' + leagueId, 'sleeperHelper.username']);
      if (!state.username && saved['sleeperHelper.username']) state.username = saved['sleeperHelper.username'];
      const prefs = saved['sleeperSeason_' + leagueId] || {};
      if (prefs.rosterId) state.myLeagueRosterId = prefs.rosterId;
      if (prefs.tab) state.seasonTab = prefs.tab === 'picks' ? 'sims' : prefs.tab; // v0.14 tab id migration
      if (prefs.posFilter) state.seasonPosFilter = prefs.posFilter;
      if (prefs.teamSrc && SOURCES[prefs.teamSrc]) state.seasonTeamSrc = prefs.teamSrc;
      await ensureNflState();
      state.seasonLeague = await api('/league/' + leagueId);
      // League scoring drives BOTH the lineup optimizer and waiver deltas:
      // pPg/szn re-baked to this league's rec / pass_td / TE-premium values.
      applyLeagueScoring(state.seasonLeague && state.seasonLeague.scoring_settings);
      const rp = (state.seasonLeague && state.seasonLeague.roster_positions) || [];
      const sf = rp.indexOf('SUPER_FLEX') !== -1 || rp.filter((s) => s === 'QB').length >= 2;
      const dynasty = !!(state.seasonLeague && state.seasonLeague.settings && state.seasonLeague.settings.type >= 1);
      state.modeDetected = (dynasty ? 'dyn' : 're') + '_' + (sf ? 'sf' : '1qb');
      if (!state.modeManual) applyMode(state.modeDetected, false);
      await refreshLeagueData();
      if (!state.myLeagueRosterId) await findSeasonTeam();
      startSeasonPolling();
      startDecorating(); // league TEAM page rows get matchup/ppg/verdict pills
      fetchInjuries();
      fetchTrending();
      fetchSeasonStats(); // in-season: decay preseason projections toward actuals
      // fresh league = fresh sim; kick it now if SIMS is the saved tab
      Object.assign(state.pickSim, { status: 'idle', placeCounts: null, results: null, inv: null, recHash: null, selTeam: null });
      if (state.seasonTab === 'sims' && pkTabVisible()) setTimeout(ensurePickSim, 0);
    } catch (e) {
      state.seasonStatus = 'League load failed: ' + e.message;
    }
    render();
  }
  function startSeasonPolling() {
    stopSeasonPolling();
    state.seasonPollTimer = setInterval(async () => {
      if (state.appMode !== 'season' || !state.seasonLeagueId) return;
      try { await refreshLeagueData(); render(); } catch (e) {}
    }, SEASON_POLL_MS);
  }
  function stopSeasonPolling() {
    if (state.seasonPollTimer) { clearInterval(state.seasonPollTimer); state.seasonPollTimer = null; }
  }
  function setAppMode(mode) {
    if (mode === state.appMode) { render(); return; }
    state.appMode = mode;
    store.set({ 'sleeperHelper.appMode': mode });
    if (mode === 'season') {
      const lid = detectLeagueId() || (state.draft && state.draft.league_id) || state.seasonLeagueId;
      if (lid && lid !== state.seasonLeagueId) { initForLeague(lid); return; }
      if (!state.seasonLeagueId) loadMyLeagues();
    }
    render();
  }

  // ---------- UI ----------
  let root = null;
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }
  function fmtVal(v) { return v == null ? '—' : String(v); }

  function buildPanel() {
    if (root) return;
    root = document.createElement('div');
    root.id = 'mff-sidebar';
    root.innerHTML = `
      <div id="mff-header">
        <span class="title">MFF SLEEPER HELPER</span>
        <div id="mff-appmode">
          <button data-appmode="draft" title="Live draft tracking">DRAFT</button>
          <button data-appmode="season" title="Weekly lineup + waivers for a league">SEASON</button>
        </div>
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
    root.querySelectorAll('#mff-appmode button').forEach((b) => {
      b.addEventListener('click', () => setAppMode(b.dataset.appmode));
    });
    root.querySelector('#mff-close').addEventListener('click', hidePanel);
    enableDrag();
    enableResize();
    root.querySelector('#mff-body').addEventListener('click', onBodyClick);
    root.querySelector('#mff-body').addEventListener('change', onBodyChange);
    root.querySelector('#mff-body').addEventListener('input', onBodyInput);
  }
  function destroyPanel() {
    if (root) { root.remove(); root = null; }
    const chip = document.getElementById('mff-reopen');
    if (chip) chip.remove();
    stopPolling();
    stopSeasonPolling();
    stopDecorating();
  }

  // ✕ hides the panel; a small floating chip brings it back without a reload.
  function hidePanel() {
    if (!root) return;
    root.style.display = 'none';
    if (document.getElementById('mff-reopen')) return;
    const chip = document.createElement('div');
    chip.id = 'mff-reopen';
    chip.textContent = 'MFF';
    chip.title = 'Show MFF Sleeper Helper';
    chip.style.cssText = 'position:fixed;bottom:18px;right:18px;z-index:2147483647;' +
      'background:#00ceb8;color:#0b1220;font:700 11px -apple-system,BlinkMacSystemFont,sans-serif;' +
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
    // mode: 'se' corner, 'e' width, 's' height, 'n' top edge (bottom pinned)
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
    state._rendered = true;
    const body = root.querySelector('#mff-body');
    if (!gateAllowed()) { body.innerHTML = gateLockHTML(); return; }
    const recsEl = body.querySelector('#mff-recs');
    const scrollTop = recsEl ? recsEl.scrollTop : 0;
    const searchFocused = document.activeElement && document.activeElement.id === 'mff-search';
    root.classList.toggle('on-clock',
      state.appMode === 'draft' && state.tracking && picksUntilMine() === 0);
    root.querySelectorAll('#mff-appmode button').forEach((b) => {
      b.classList.toggle('active', b.dataset.appmode === state.appMode);
    });
    body.innerHTML = state.appMode === 'season' ? seasonHTML()
      : state.tracking ? trackingHTML() : setupHTML();
    const newRecs = body.querySelector('#mff-recs');
    if (newRecs) newRecs.scrollTop = scrollTop;
    if (searchFocused) {
      const inp = body.querySelector('#mff-search');
      if (inp) {
        inp.focus();
        inp.setSelectionRange(inp.value.length, inp.value.length);
      }
    }
  }
  function renderStatusOnly() {
    if (!root) return;
    const el = root.querySelector('#mff-status-line');
    if (el) el.textContent = state.appMode === 'season' ? state.seasonStatus : state.statusMsg;
  }

  function setupHTML() {
    const d = state.draft;
    const teams = d && d.settings ? d.settings.teams : 12;
    let slots = '';
    for (let i = 1; i <= teams; i++) {
      slots += `<button data-slot="${i}" class="${state.mySlot === i ? 'active' : ''}">${i}</button>`;
    }
    const draftInfo = d
      ? `${d.type || 'snake'} · ${d.settings.teams} teams · ${d.settings.rounds} rds${d.settings.reversal_round ? ' · 3RR@' + d.settings.reversal_round : ''}`
      : (state.draftId ? 'loading draft…' : 'open a Sleeper draft room');
    return `
      <div id="mff-setup">
        <label>Draft: <b>${esc(draftInfo)}</b></label>
        <label>Format ${state.modeDetected ? (state.modeDetected === state.mode && !state.modeManual ? '<span style="color:#22c55e">(auto-detected)</span>' : '(detected: ' + esc(MODES[state.modeDetected].label) + ')') : ''}</label>
        <select class="mff-select" id="mff-mode" style="background:#26304d;border:1px solid #33406a;color:#eef1f9;padding:4px 6px;border-radius:3px;font-size:11px;font-weight:600">
          ${modeOptions()}
        </select>
        <label>Sleeper username (auto-finds your slot)</label>
        <div style="display:flex;gap:4px">
          <input type="text" id="mff-username" value="${esc(state.username)}" placeholder="username"
            style="flex:1;background:#0b1220;border:1px solid #26304d;color:#eef1f9;padding:5px 8px;border-radius:4px;font-size:12px">
          <button id="mff-find-slot" style="background:#26304d;border:none;color:#eef1f9;padding:5px 10px;border-radius:4px;cursor:pointer;font-weight:600">FIND</button>
        </div>
        <label>…or pick your draft slot</label>
        <div class="slot-row">${slots}</div>
        <button class="start-btn" id="mff-start" ${state.mySlot && state.draftId ? '' : 'disabled'}>Start Tracking</button>
        <div style="font-size:10px;color:#8b94b3">${esc(state.statusMsg)}</div>
      </div>`;
  }

  function pickLineHTML() {
    const d = state.draft;
    const teams = d.settings.teams;
    const nextNo = state.picks.length + 1;
    const rd = Math.ceil(nextNo / teams);
    const rdPick = ((nextNo - 1) % teams) + 1;
    const until = picksUntilMine();
    const untilTxt = until == null ? '' :
      until === 0 ? '<span class="pl-until on-clock">ON THE CLOCK</span>' :
      `<span class="pl-until">${until} until you</span>`;
    const done = d.settings && nextNo > teams * d.settings.rounds;
    return `
      <div id="mff-pick-line">
        ${done ? '<span class="pl-pick">DRAFT COMPLETE</span>' : `
        <span class="pl-pick">Pick ${rd}.${String(rdPick).padStart(2, '0')}</span>
        <span class="pl-sep">·</span><span class="pl-round">#${nextNo}</span>
        <span class="pl-sep">·</span><span class="pl-mine">You: ${state.myRoster.length}</span>
        ${untilTxt ? '<span class="pl-sep">·</span>' + untilTxt : ''}`}
      </div>`;
  }

  function tickerHTML() {
    const last = state.picks.slice(-3).reverse();
    if (!last.length) return '';
    const t = state.draft.settings.teams;
    return '<div style="font-size:9px;color:#8b94b3;display:flex;flex-direction:column;gap:1px;padding:0 2px">' +
      last.map((pk) => {
        const rd = Math.ceil(pk.pick_no / t), rp = ((pk.pick_no - 1) % t) + 1;
        const md = pk.metadata || {};
        const who = state.userNames[pk.picked_by] || ('Slot ' + pk.draft_slot);
        const nm = ((md.first_name || '') + ' ' + (md.last_name || '')).trim();
        return `<div>${rd}.${String(rp).padStart(2, '0')} <b style="color:#cbd2e6">${esc(nm)}</b> ${esc(md.position || '')} <span style="color:#5b6485">— ${esc(who)}</span></div>`;
      }).join('') + '</div>';
  }

  // UD's "REMAINING" target row, driven by the league's real starter slots
  // (superflex counts toward QB).
  function remainingStartersHTML() {
    const st = (state.draft && state.draft.settings) || {};
    const c = rosterCounts();
    const req = {
      QB: (st.slots_qb || 0) + (st.slots_super_flex || 0),
      RB: st.slots_rb || 0,
      WR: st.slots_wr || 0,
      TE: st.slots_te || 0,
    };
    if (!req.QB && !req.RB && !req.WR && !req.TE) return '';
    const cells = ['QB', 'RB', 'WR', 'TE'].map((pos) =>
      `<div class="pos pos-${pos.toLowerCase()}"><span class="v">${Math.max(0, req[pos] - c[pos])}</span><span class="l">${pos}</span></div>`
    ).join('');
    return `<div id="mff-target-row">${cells}</div>`;
  }

  function recommendedHTML() {
    const recs = recommendPicks();
    if (!recs.length) return '';
    const MEDALS = ['#00ceb8', '#c0c7d1', '#c9926b'];
    const cards = recs.map((r, i) => {
      const p = r.p;
      const k = keyOf(p);
      const expanded = state.expandedKey === 'rec|' + k;
      const team = p.sTm || p.t || '';
      const reasonTags = r.reasons.map((t) => {
        const cls = t.indexOf('STEAL') === 0 ? 'STEAL' : t.indexOf('Value') === 0 ? 'Value' : t.indexOf('Reach') === 0 ? 'Reach' : '';
        return `<span class="tag ${cls}">${esc(t)}</span>`;
      }).join('');
      return `
      <div class="mff-rec ${i === 0 ? 'top' : ''}" data-key="rec|${esc(k)}">
        <div class="num" style="color:${MEDALS[i]};font-weight:800">${i + 1}</div>
        <div class="info">
          <div class="name">${esc(p.n)} ${injTagHTML(p)}</div>
          <div class="meta">
            <span class="pos ${p.s}">${p.s}</span>
            <span>${esc(team)}</span>
            ${p.pPg != null ? `<span>${p.pPg}ppg</span>` : ''}
            ${p[modeKeys().adp] != null ? `<span>ADP ${p[modeKeys().adp]}</span>` : ''}
          </div>
          ${reasonTags ? `<div class="why">${reasonTags}</div>` : ''}
        </div>
        <div class="score" style="color:${MEDALS[i]}">${r.score}</div>
        ${expanded ? profileHTML(p, k) : ''}
      </div>`;
    }).join('');
    return `<div class="mff-section" id="mff-recommended-wrap"><h3>Recommended</h3>${cards}</div>`;
  }


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
    try { if (state._rendered) render(); } catch (_) {}
  }
  try {
    chrome.storage.local.get(['mff_my_rankings'], (res) => _applyMyRanks(res && res.mff_my_rankings));
    chrome.storage.onChanged.addListener((ch, area) => {
      if (area === 'local' && ch.mff_my_rankings) _applyMyRanks(ch.mff_my_rankings.newValue);
    });
  } catch (_) {}
  function draftTabHTML() {
    if (state.rankSource === 'mine' && !myRanksAvailable()) state.rankSource = 'jack';
    let srcOpts = '';
    for (const [k, s] of Object.entries(SOURCES)) {
      if (k === 'mine' && !myRanksAvailable()) continue;
      srcOpts += `<option value="${k}" ${state.rankSource === k ? 'selected' : ''}>${s.label}</option>`;
    }
    const posChips = ['ALL', 'QB', 'RB', 'WR', 'TE', 'K', 'DST', 'PK'].map((p) =>
      `<button class="pos-filter ${state.posFilter === p ? 'active' : ''}" data-pos="${p}">${p}</button>`
    ).join('');
    return `
      ${pickLineHTML()}
      ${tickerHTML()}
      <div class="mff-section" id="mff-roster-wrap">
        <h3>My Roster</h3>
        ${countsGridHTML()}
        ${remainingStartersHTML()}
      </div>
      ${recommendedHTML()}
      <div class="mff-section" id="mff-recs-wrap">
        <h3>Available</h3>
        <div id="mff-toggle-row">
          <select class="mff-select" id="mff-mode">${modeOptions()}</select>
          <select class="mff-select" id="mff-rank-source">${srcOpts}</select>
        </div>
        <div id="mff-pos-toggle" style="display:flex;gap:3px;margin-bottom:4px">${posChips}
          <button id="mff-sort-vor" class="pos-filter ${state.sortVor ? 'active' : ''}" title="Sort by VOR (format-aware)" style="flex:0 0 auto">VOR</button>
        </div>
        <div id="mff-recs">${state.posFilter === 'PK' ? pickAssetsHTML() : recsHTML()}</div>
      </div>
      <div id="mff-manual">
        <input type="text" id="mff-search" placeholder="Search player… (✕ drafted / ＋ my pick)" value="${esc(state.searchQ)}" autocomplete="off">
        <div id="mff-suggestions" style="${state.searchQ.length >= 2 ? '' : 'display:none'}">${searchSuggestionsHTML()}</div>
      </div>`;
  }

  function sortListBySource(list) {
    const src = SOURCES[state.rankSource];
    return list.slice().sort((a, b) => {
      const va = src.get(a), vb = src.get(b);
      if (va == null && vb == null) return a.rank - b.rank;
      if (va == null) return 1;
      if (vb == null) return -1;
      return src.desc ? vb - va : va - vb;
    });
  }

  // Rostered stacks + best available stack partners for each of my QBs.
  function stacksSectionHTML() {
    const qbs = state.myRoster.filter((r) => r.pos === 'QB' && r.p && r.p.sTm);
    let inner;
    if (!qbs.length) {
      inner = '<div class="mff-proj-empty">Draft a QB to see stack partners</div>';
    } else {
      inner = qbs.map((qb) => {
        const tm = qb.p.sTm;
        const have = state.myRoster.filter((r) => r !== qb && r.p && r.p.sTm === tm);
        const targets = sortListBySource(
          availablePlayers().filter((p) => p.sTm === tm && (p.s === 'WR' || p.s === 'TE'))
        ).slice(0, 3);
        const haveRows = have.map((r) =>
          `<div class="mff-proj-roster-player"><span class="t">${esc(r.pos)}</span>
            <span class="n" style="color:#58a7ff">${esc(r.name)} ✓</span>
            <span class="v">${r.p && r.p.ktcSf != null ? r.p.ktcSf : '—'}</span></div>`).join('');
        const targetRows = targets.map((t) =>
          `<div class="mff-proj-roster-player"><span class="t">${esc(t.s)}</span>
            <span class="n">${esc(t.n)}</span>
            <span class="v">${t[modeKeys().ktc] != null ? t[modeKeys().ktc] : '—'}</span></div>`).join('');
        return `<div class="mff-proj-roster-group">
          <div class="mff-proj-roster-grouphead" style="color:#58a7ff">${esc(qb.name)} <span class="ct">(${esc(tm)})</span></div>
          ${haveRows}
          ${targetRows || '<div class="mff-proj-empty" style="padding:4px">No pass-catchers left on ' + esc(tm) + '</div>'}
        </div>`;
      }).join('');
    }
    return `<div class="mff-section"><h3>Stacks</h3><div class="mff-proj-roster">${inner}</div></div>`;
  }

  function rosterTabHTML() {
    // PPG-by-position grid (Clay ½PPR sums of rostered players)
    const sums = { QB: 0, RB: 0, WR: 0, TE: 0 };
    const counts = { QB: 0, RB: 0, WR: 0, TE: 0 };
    for (const r of state.myRoster) {
      if (sums[r.pos] == null || !r.p || r.p.pPg == null) continue;
      sums[r.pos] += r.p.pPg;
      counts[r.pos]++;
    }
    const POS_COLORS = { QB: '#ff2a6d', RB: '#00ceb8', WR: '#58a7ff', TE: '#ffae58' };
    const grid = ['QB', 'RB', 'WR', 'TE'].map((pos) => `
      <div class="mff-proj-cell" style="border-top-color:${POS_COLORS[pos]}">
        <div class="mff-proj-pos" style="color:${POS_COLORS[pos]}">${pos}</div>
        <div class="mff-proj-val">${Math.round(sums[pos] * 10) / 10}</div>
        <div class="mff-proj-sub">${counts[pos]} proj'd</div>
      </div>`).join('');
    return `
      ${pickLineHTML()}
      <div class="mff-section">
        <h3>My Roster</h3>
        ${countsGridHTML()}
        ${remainingStartersHTML()}
      </div>
      <div class="mff-section">
        <h3>Proj PPG by position</h3>
        <div class="mff-proj-grid">${grid}</div>
      </div>
      ${stacksSectionHTML()}
      ${rosterListHTML()}`;
  }

  function settingsTabHTML() {
    const d = state.draft;
    const teams = d && d.settings ? d.settings.teams : 12;
    let slots = '';
    for (let i = 1; i <= teams; i++) {
      slots += `<button data-slot="${i}" class="${state.mySlot === i ? 'active' : ''}">${i}</button>`;
    }
    const draftInfo = d
      ? `${d.type || 'snake'} · ${d.settings.teams} teams · ${d.settings.rounds} rds${d.settings.reversal_round ? ' · 3RR@' + d.settings.reversal_round : ''}`
      : '—';
    let ver = '';
    try { ver = chrome.runtime.getManifest().version; } catch (e) {}
    return `
      ${pickLineHTML()}
      <div class="mff-section"><h3>Draft</h3>
        <div style="font-size:11px;color:#cbd2e6">${esc(draftInfo)}</div></div>
      <div class="mff-section"><h3>Sleeper username</h3>
        <div style="display:flex;gap:4px">
          <input type="text" id="mff-username" value="${esc(state.username)}" placeholder="username"
            style="flex:1;background:#0b1220;border:1px solid #26304d;color:#eef1f9;padding:5px 8px;border-radius:4px;font-size:12px">
          <button id="mff-find-slot" style="background:#26304d;border:none;color:#eef1f9;padding:5px 10px;border-radius:4px;cursor:pointer;font-weight:600">FIND</button>
        </div></div>
      <div class="mff-section"><h3>Draft slot</h3>
        <div id="mff-slot-grid-settings">${slots}</div></div>
      <label style="display:flex;align-items:center;gap:6px;font-size:11px;color:#cbd2e6;cursor:pointer">
        <input type="checkbox" id="mff-notify" ${state.notify ? 'checked' : ''}>
        Notify me when my pick is ≤1 away (works with the tab closed)
      </label>
      <button id="mff-start" class="start-btn" style="background:#00ceb8;border:none;color:#0b1220;padding:8px;border-radius:4px;cursor:pointer;font-weight:700;text-transform:uppercase;letter-spacing:0.5px" ${state.mySlot ? '' : 'disabled'}>Apply + Resync</button>
      <div style="font-size:10px;color:#8b94b3">Players: ${state.players.length} · data ${esc(state.exportedAt)}${ver ? ' · v' + ver : ''}</div>`;
  }

  // ---------- RULES tab: draft-rules checklist + platform value board ----------
  // The rules are Jack's redraft doctrine, checked LIVE against the roster:
  // each one is pending (○) until its window closes, then locks ✓/✗. Rounds
  // come from the pick's real overall slot (manual adds fall back to pick
  // order) so trades/keeper slots don't skew the windows.
  const PLATFORM_RANK = { field: 'slR', label: 'Sleeper' };
  function draftRules() {
    const ds = (state.draft && state.draft.settings) || {};
    const teams = ds.teams || 12;
    const rounds = ds.rounds || 15;
    const sf = state.mode.endsWith('_sf');
    const picks = state.myRoster.slice().sort((a, b) => (a.pickNo || 1e9) - (b.pickNo || 1e9));
    const rdOf = (r, i) => (r.pickNo ? Math.ceil(r.pickNo / teams) : i + 1);
    const made = picks.length; // my rounds completed (snake = one pick a round)
    const cntThru = (pos, thruRd) =>
      picks.filter((r, i) => r.pos === pos && rdOf(r, i) <= thruRd).length;
    const rules = [];
    const add = (label, status, detail, tip) => rules.push({ label, status, detail, tip });

    if (!sf) {
      const earlyQB = picks.map((r, i) => ({ r, rd: rdOf(r, i) }))
        .find((x) => x.r.pos === 'QB' && x.rd <= 5);
      add('Fade early-round QB',
        earlyQB ? 'fail' : (made >= 5 ? 'pass' : 'track'),
        earlyQB ? 'QB taken Rd ' + earlyQB.rd : (made >= 5 ? 'No QB in Rds 1-5' : 'On track — no QB yet'),
        'QB is deep — mid-round QBs score nearly as much as the early ones. Best value lands Rd 6+.');
    } else {
      const q8 = cntThru('QB', 8);
      add('2 QBs through 8 rounds (SF)',
        q8 >= 2 ? 'pass' : (made >= 8 ? 'fail' : 'track'),
        q8 + '/2 QBs' + (made > 0 && made < 8 && q8 < 2 ? ' · thru Rd ' + made : ''),
        'Superflex flips the QB rule: QB is the scarcest asset — leave Rd 8 with two starters.');
    }

    const rb3 = cntThru('RB', 3);
    add('2 RBs through 3 rounds',
      rb3 >= 2 ? 'pass' : (made >= 3 ? 'fail' : 'track'),
      rb3 + '/2 RBs' + (made > 0 && made < 3 && rb3 < 2 ? ' · thru Rd ' + made : ''),
      'RB value falls off a cliff after Rd 2 — leave Rd 3 with two you trust.');

    const wr8 = cntThru('WR', 8);
    add('4 WRs through 8 rounds',
      wr8 >= 4 ? 'pass' : (made >= 8 ? 'fail' : 'track'),
      wr8 + '/4 WRs' + (made > 0 && made < 8 && wr8 < 4 ? ' · thru Rd ' + made : ''),
      'WR volume wins leagues — four by Rd 8 keeps the flex strong and survives busts.');

    const dbl = picks.map((r, i) => ({ r, rd: rdOf(r, i) }))
      .filter((x) => x.rd < 10 && (x.r.pos === 'TE' || (!sf && x.r.pos === 'QB')))
      .reduce((m, x) => { m[x.r.pos] = (m[x.r.pos] || 0) + 1; return m; }, {});
    const dblPos = Object.keys(dbl).find((pos) => dbl[pos] >= 2);
    add(sf ? 'One TE is enough early' : 'One QB / one TE is enough',
      dblPos ? 'fail' : (made >= 9 ? 'pass' : 'track'),
      dblPos ? '2nd ' + dblPos + ' before Rd 10' : 'No doubles before Rd 10',
      'Your starter closes the position — a backup ' + (sf ? 'TE' : 'QB or TE') +
      ' before Rd 10 costs a WR/RB pick that actually plays.');

    const lateRd = rounds - 2;
    const earlyKD = picks.map((r, i) => ({ r, rd: rdOf(r, i) }))
      .find((x) => (x.r.pos === 'K' || x.r.pos === 'DST') && x.rd <= lateRd);
    add('K + DST in the last 2 rounds',
      earlyKD ? 'fail' : (made >= lateRd ? 'pass' : 'track'),
      earlyKD ? earlyKD.r.pos + ' taken Rd ' + earlyKD.rd : 'None before Rd ' + (lateRd + 1),
      'K and D/ST barely repeat year to year — stream them; never spend a real pick.');

    return rules;
  }
  // Platform value board: where Sleeper's own draft-room rank disagrees with
  // Jack's board the most. Positive gap = Sleeper underrates him (he'll come
  // cheap in this room — TARGET); negative = the room will overpay (TRAP).
  // Redraft modes only: slR is a redraft list, so it's compared against
  // Jack's redraft board.
  function platformValueOf(p) {
    if (state.mode.indexOf('re_') !== 0) return null;
    if (p.s === 'K' || p.s === 'DST') return null; // K/DST rank scales don't compare
    const plat = p[PLATFORM_RANK.field], jack = p.rank;
    if (plat == null || jack == null) return null;
    const diff = plat - jack;
    const thresh = Math.max(8, Math.round(0.25 * Math.min(plat, jack)));
    if (diff >= thresh) return { verdict: 'good', diff, plat, jack };
    if (-diff >= thresh) return { verdict: 'bad', diff, plat, jack };
    return null;
  }
  function platformValueBoard() {
    // Only names inside the truly draftable range matter — a +200 gap on a
    // late-bench player is trivia, not a draft plan. Hard cap at Jack's top
    // 150 (per Jack: nobody should draft outside that range), tighter if the
    // room itself is smaller. TARGETS gate on Jack's rank (would WE draft
    // him); TRAPS gate on the platform's rank (will the ROOM draft him —
    // Jack ranking him deep is exactly what makes it a trap).
    const ds = (state.draft && state.draft.settings) || {};
    const cap = Math.min(150, (ds.teams || 12) * (ds.rounds || 15));
    const rows = [];
    for (const p of availablePlayers()) {
      const v = platformValueOf(p);
      if (!v) continue;
      if (v.verdict === 'good' ? v.jack <= cap : v.plat <= cap) rows.push({ p, v });
    }
    return {
      targets: rows.filter((r) => r.v.verdict === 'good')
        .sort((a, b) => b.v.diff - a.v.diff).slice(0, 8),
      fades: rows.filter((r) => r.v.verdict === 'bad')
        .sort((a, b) => a.v.diff - b.v.diff).slice(0, 5),
    };
  }
  function valueRowHTML(row, i) {
    const p = row.p, v = row.v, k = keyOf(p);
    const good = v.verdict === 'good';
    const col = good ? '#6dd06d' : '#d06d6d';
    return `
      <div class="mff-rec" data-key="${esc(k)}">
        <div class="num" style="color:${col}">${i + 1}</div>
        <div class="info">
          <div class="name">${esc(p.n)}</div>
          <div class="meta">
            <span class="pos ${p.s}">${p.s}</span>
            <span>${esc(p.sTm || p.t || '')}</span>
            <span>${PLATFORM_RANK.label} #${v.plat}</span>
            <span>Jack #${v.jack}</span>
            ${p.pPg != null ? `<span>${p.pPg}ppg</span>` : ''}
          </div>
        </div>
        <div class="score" style="color:${col}" title="${PLATFORM_RANK.label} rank minus Jack's rank — ${good ? 'the room will let him fall to you' : 'the room will take him way before Jack would'}">${good ? '+' : ''}${v.diff}</div>
        ${state.expandedKey === k ? profileHTML(p, k) : ''}
      </div>`;
  }
  const RULE_ICONS = { pass: ['✓', '#6dd06d'], fail: ['✗', '#d06d6d'], track: ['○', '#8b94b3'] };
  function rulesTabHTML() {
    const ruleRows = draftRules().map((r) => {
      const [icon, col] = RULE_ICONS[r.status];
      return `<div title="${esc(r.tip)}" style="display:flex;gap:7px;align-items:baseline;padding:4px 2px;border-bottom:1px solid #1d2438">
        <span style="color:${col};font-weight:800;flex:0 0 12px">${icon}</span>
        <span style="flex:1;font-size:11px;font-weight:600;color:${r.status === 'fail' ? '#d06d6d' : '#eef1f9'}">${esc(r.label)}</span>
        <span style="font-size:10px;color:${col}">${esc(r.detail)}</span>
      </div>`;
    }).join('');
    let valueHtml = '';
    if (state.mode.indexOf('re_') === 0) {
      const vb = platformValueBoard();
      const tgt = vb.targets.length
        ? vb.targets.map(valueRowHTML).join('')
        : '<div class="mff-proj-empty">No big gaps left on the board</div>';
      valueHtml = `
      <div class="mff-section"><h3>Targets — ${PLATFORM_RANK.label} undervalues</h3>
        <div style="font-size:10px;color:#8b94b3;padding:0 2px 4px">Jack ranks them far above ${PLATFORM_RANK.label}'s own list — the room lets them fall</div>
        ${tgt}
      </div>` + (vb.fades.length ? `
      <div class="mff-section"><h3>Traps — ${PLATFORM_RANK.label} overvalues</h3>
        <div style="font-size:10px;color:#8b94b3;padding:0 2px 4px">${PLATFORM_RANK.label}'s list will make someone pay ${PLATFORM_RANK.label}'s price — don't let it be you</div>
        ${vb.fades.map(valueRowHTML).join('')}
      </div>` : '');
    } else {
      valueHtml = '<div class="mff-section"><h3>Targets</h3><div class="mff-proj-empty">Value board is redraft-only (' +
        PLATFORM_RANK.label + "'s room rank is a redraft list)</div></div>";
    }
    return `
      ${pickLineHTML()}
      <div class="mff-section"><h3>Draft Rules</h3>
        <div style="font-size:10px;color:#8b94b3;padding:0 2px 4px">Checked live against your picks — hover a rule for the why</div>
        ${ruleRows}
      </div>
      ${valueHtml}`;
  }

  function trackingHTML() {
    const tabs = [['draft', 'DRAFT'], ['roster', 'ROSTER'], ['rules', 'RULES'], ['settings', 'SETTINGS']].map(([id, lbl]) =>
      `<button class="mff-tab ${state.tab === id ? 'active' : ''}" data-tab="${id}">${lbl}</button>`).join('');
    const content = state.tab === 'roster' ? rosterTabHTML()
      : state.tab === 'settings' ? settingsTabHTML()
      : state.tab === 'rules' ? rulesTabHTML()
      : draftTabHTML();
    return `
      <div id="mff-tabs">${tabs}</div>
      ${content}
      <div id="mff-mode-line" style="display:flex;gap:6px;font-size:10px;color:#8b94b3;align-items:center">
        <span class="badge live" style="background:#2a4030;color:#6dd06d;padding:2px 6px;border-radius:3px;letter-spacing:0.5px;text-transform:uppercase;font-weight:600">LIVE API</span>
        <span id="mff-status-line" style="flex:1">${esc(state.statusMsg)}</span>
      </div>`;
  }

  // Injury chip — clickable (opens the detail popover below) wherever it
  // renders: season lineup/waiver rows AND draft rec rows.
  function injTagHTML(p) {
    const m = p && p.sid && state.slMeta[p.sid];
    if (!m || !m.inj) return '';
    const cfg = m.inj === 'OUT' ? ['#402a2a', '#d06d6d', 'OUT']
      : m.inj === 'D' ? ['#453325', '#e0a060', 'DTD']
      : ['#4a3f30', '#ffc99b', 'Q'];
    return `<span class="tag mff-inj-tag" data-sid="${esc(String(p.sid))}" title="Click for injury detail" style="background:${cfg[0]};color:${cfg[1]};cursor:pointer">${cfg[2]}</span>`;
  }
  // ---------- season-mode UI ----------
  function snBadges(p) {
    let out = '';
    if (onByeThisWeek(p)) {
      out += '<span class="tag" style="background:#3a3040;color:#c0a0d0">BYE</span>';
    }
    out += injTagHTML(p);
    return out;
  }
  // Injury detail popover: anchored to the clicked chip, appended to the host
  // page body (the sidebar re-renders its innerHTML too often to own it).
  function showInjPopover(sid, anchor) {
    let pop = document.getElementById('mff-inj-popover');
    if (!pop) {
      pop = document.createElement('div');
      pop.id = 'mff-inj-popover';
      document.body.appendChild(pop);
      document.addEventListener('click', (e) => {
        if (pop.style.display === 'block' && !pop.contains(e.target) && !e.target.closest('.mff-inj-tag')) pop.style.display = 'none';
      }, true);
      document.addEventListener('keydown', (e) => { if (e.key === 'Escape') pop.style.display = 'none'; });
      window.addEventListener('scroll', () => { pop.style.display = 'none'; }, true);
    }
    if (pop.style.display === 'block' && pop._sid === sid) { pop.style.display = 'none'; return; }
    const m = state.slMeta[sid];
    if (!m) return;
    const rows = [];
    rows.push(['Status', m.is || (m.inj === 'OUT' ? 'Out' : m.inj === 'D' ? 'Doubtful' : 'Questionable')]);
    if (m.st) rows.push(['Roster', m.st]);
    rows.push(['Injury', m.ib || 'Undisclosed']);
    if (m.idt) rows.push(['Since', m.idt]);
    if (m.inx) rows.push(['Note', m.inx]);
    pop.innerHTML = '<div class="mip-name">' + esc(m.n || '') + '</div>'
      + '<div class="mip-grid">' + rows.map((r) => '<span class="mip-k">' + esc(r[0]) + '</span><span>' + esc(r[1]) + '</span>').join('') + '</div>'
      + '<div class="mip-foot">Sleeper injury feed</div>';
    pop._sid = sid;
    pop.style.display = 'block';
    const r = anchor.getBoundingClientRect();
    const pw = pop.offsetWidth;
    let left = r.left + window.scrollX - 10;
    left = Math.min(Math.max(8, left), window.scrollX + document.documentElement.clientWidth - pw - 8);
    pop.style.left = left + 'px';
    pop.style.top = (r.bottom + window.scrollY + 6) + 'px';
  }
  document.addEventListener('click', (e) => {
    const tag = e.target.closest && e.target.closest('.mff-inj-tag');
    if (!tag) return;
    e.stopPropagation();
    e.preventDefault();
    showInjPopover(tag.getAttribute('data-sid'), tag);
  }, true);
  function seasonHeaderHTML() {
    const lg = state.seasonLeague;
    const name = lg ? lg.name : 'League';
    const modeLbl = MODES[state.mode] ? MODES[state.mode].label : '';
    const hasProps = !!(state.wkPropsAll && state.wkPropsAll[String(state.seasonWeek)]);
    return `
      <div id="mff-pick-line">
        <span class="pl-pick">${esc(name)}</span>
        <span class="pl-sep">·</span><span class="pl-round">Wk ${state.seasonWeek}${state.byesActive ? '' : ' (pre)'}</span>
        <span class="pl-sep">·</span><span class="pl-mine">${esc(state.scoringLabel)}</span>
        <span class="pl-sep">·</span><span class="pl-mine">${esc(modeLbl)}</span>
        ${hasProps ? '<span class="pl-sep">·</span><span class="pl-mine" style="color:#6dd06d" title="Wk ' + state.seasonWeek + ' prop boards (UD+PP) loaded — weekly values are the sim-engine mean (Vegas priced in); props cover players outside the engine">W' + state.seasonWeek + ' props</span>' : ''}
      </div>`;
  }
  function seasonLineupHTML() {
    if (!myRosterDoc()) {
      return '<div class="mff-proj-empty">Pick your team in SETTINGS' +
        (state.username ? '' : ' (set your username first)') + '</div>';
    }
    const calc = seasonLineupCalc();
    const pool = calc.pool;
    const opt = calc.opt;
    const starterSet = calc.starterSet;
    const moves = calc.moves;
    const optIds = new Set(opt.assign.filter((a) => a.e && a.e.p.sid).map((a) => a.e.p.sid));
    // Row verdicts: green = should be starting (isn't), red = should sit
    // (is starting), orange = the swap is a toss-up (<1.5 ppg apart).
    const rowCls = {};
    for (const k of Object.keys(calc.cls)) rowCls[k] = 'mff-row-' + calc.cls[k];
    const POS_COLORS = { QB: '#ff2a6d', RB: '#00ceb8', WR: '#58a7ff', TE: '#ffae58', K: '#bd66ff', DEF: '#7988a1' };
    const rows = opt.assign.map((a) => {
      const slotLbl = a.slot === 'SUPER_FLEX' ? 'SFLX' : a.slot === 'WRRB_FLEX' ? 'W/R'
        : a.slot === 'REC_FLEX' ? 'W/T' : a.slot === 'DEF' ? 'DST' : a.slot;
      const col = POS_COLORS[a.slot] || '#8b94b3';
      if (!a.e) {
        return `<div class="mff-proj-roster-player"><span class="t" style="color:${col}">${esc(slotLbl)}</span>
          <span class="n" style="color:#d06d6d">— empty${SLOT_ELIG[a.slot] ? '' : ' (unsupported slot)'}</span><span class="v"></span></div>`;
      }
      const p = a.e.p;
      const k = keyOf(p);
      const cls = rowCls[k] || '';
      const starting = p.sid && starterSet.has(p.sid);
      const mark = starting ? '<span style="color:#5b6485">✓</span>'
        : cls === 'mff-row-close'
          ? '<span style="color:#ffc166;font-weight:800" title="Toss-up — projections are very close">≈</span>'
          : '<span style="color:#6dd06d;font-weight:800" title="Currently on your bench — start him">▲</span>';
      return `<div class="mff-proj-roster-player mff-rec ${cls}" data-key="${esc(k)}" style="cursor:pointer">
        <span class="t" style="color:${col}">${esc(slotLbl)}</span>
        <span class="n">${mark} ${esc(p.n)} ${wkOppHTML(p)}${bbTagHTML(p, a.e.v)}${snBadges(p)}${p._unmatched ? ' <span style="color:#8b94b3;font-size:9px">(no proj)</span>' : ''}</span>
        <span class="v" title="Projected ppg this week (${esc(state.scoringLabel)})">${a.e.v ? a.e.v.toFixed(1) : '0'}</span>
        ${state.expandedKey === k && !p._unmatched ? profileHTML(p, k) : ''}
      </div>`;
    }).join('');
    let movesHtml = '';
    if (moves.length) {
      movesHtml = '<div class="mff-section"><h3>Start / Sit moves</h3>' + moves.map((mv) => {
        const isClose = mv.sit && mv.delta != null && Math.abs(mv.delta) < CLOSE_PPG;
        if (isClose) {
          return `<div style="font-size:11px;color:#ffc166;padding:2px 2px">≈ Toss-up: <b>${esc(mv.add.p.n)}</b> / <b>${esc(mv.sit.p.n)}</b> <span style="color:#8b94b3">(${mv.delta >= 0 ? '+' : ''}${mv.delta.toFixed(1)})</span></div>`;
        }
        const sitTxt = mv.sit ? ' over <b style="color:#d06d6d">' + esc(mv.sit.p.n) + '</b>' : '';
        const d = mv.delta != null && mv.delta > 0 ? ` <span class="tag STEAL">+${mv.delta.toFixed(1)}</span>` : '';
        return `<div style="font-size:11px;color:#cbd2e6;padding:2px 2px">▲ Start <b style="color:#6dd06d">${esc(mv.add.p.n)}</b>${sitTxt}${d}</div>`;
      }).join('') + '</div>';
    } else if (starterSet.size) {
      movesHtml = '<div class="mff-section"><h3>Start / Sit moves</h3>' +
        '<div style="font-size:11px;color:#6dd06d;padding:2px">✓ Your lineup is already optimal</div></div>';
    }
    const bench = pool.filter((p) => !p.sid || !optIds.has(p.sid))
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
        <span class="n">${mark}${esc(b.p.n)} ${wkOppHTML(b.p)}${bbTagHTML(b.p, b.v)}${snBadges(b.p)}</span>
        <span class="v" title="Projected ppg this week (${esc(state.scoringLabel)})">${b.v ? b.v.toFixed(1) : '0'}</span>
        ${state.expandedKey === k && !b.p._unmatched ? profileHTML(b.p, k) : ''}
      </div>`;
    }).join('');
    return `
      ${seasonHeaderHTML()}
      ${movesHtml}
      <div class="mff-section"><h3>Optimal lineup <span style="color:#00ceb8">${opt.total} ppg</span></h3>
        <div class="mff-proj-roster">${rows}</div></div>
      <div class="mff-section"><h3>Bench</h3>
        <div class="mff-proj-roster">${benchRows || '<div class="mff-proj-empty">No bench players</div>'}</div></div>`;
  }
  function seasonWaiversHTML() {
    if (!myRosterDoc()) {
      return '<div class="mff-proj-empty">Pick your team in SETTINGS to rank waivers vs YOUR lineup</div>';
    }
    const posChips = ['ALL', 'QB', 'RB', 'WR', 'TE', 'K', 'DST'].map((p) =>
      `<button class="pos-filter ${state.seasonPosFilter === p ? 'active' : ''}" data-snpos="${p}">${p}</button>`
    ).join('');
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
      else tags.push('<span class="tag" style="background:#26304d;color:#8b94b3">DEPTH</span>');
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
        <div class="score" style="color:${upgrade ? '#6dd06d' : '#8b94b3'}">${r.delta > 0 ? '+' + r.delta.toFixed(1) : '·'}</div>
        ${expanded ? profileHTML(p, k) + dropLine : ''}
      </div>`;
    }).join('');
    const dropWatch = drops.length
      ? `<div class="mff-section"><h3>Drop watch</h3>${drops.map((d) =>
          `<div style="font-size:11px;color:#cbd2e6;padding:1px 2px">${esc(d.p.n)} <span style="color:#8b94b3">(${esc(d.p.s)} · ${d.marginal > 0 ? 'costs ' + d.marginal.toFixed(1) + ' ppg' : 'not in lineup'})</span></div>`
        ).join('')}</div>`
      : '';
    return `
      ${seasonHeaderHTML()}
      <div class="mff-section"><h3>Waiver targets <span style="color:#8b94b3;font-weight:400;font-size:9px">vs your lineup</span></h3>
        <div id="mff-pos-toggle" style="display:flex;gap:3px;margin-bottom:4px">${posChips}</div>
        <div id="mff-recs">${cards || '<div class="mff-proj-empty">No free agents matched</div>'}</div>
      </div>
      ${dropWatch}`;
  }
  function seasonSettingsHTML() {
    const teams = state.seasonRosters.map((r) => {
      const owner = state.userNames[r.owner_id] || ('Roster ' + r.roster_id);
      return `<button data-snroster="${r.roster_id}" class="pos-filter ${state.myLeagueRosterId === r.roster_id ? 'active' : ''}" style="flex:0 0 auto">${esc(owner)}</button>`;
    }).join('');
    let ver = '';
    try { ver = chrome.runtime.getManifest().version; } catch (e) {}
    return `
      ${seasonHeaderHTML()}
      <div class="mff-section"><h3>Sleeper username</h3>
        <div style="display:flex;gap:4px">
          <input type="text" id="mff-username" value="${esc(state.username)}" placeholder="username"
            style="flex:1;background:#0b1220;border:1px solid #26304d;color:#eef1f9;padding:5px 8px;border-radius:4px;font-size:12px">
          <button id="mff-sn-find" style="background:#26304d;border:none;color:#eef1f9;padding:5px 10px;border-radius:4px;cursor:pointer;font-weight:600">FIND</button>
        </div></div>
      <div class="mff-section"><h3>Your team</h3>
        <div style="display:flex;flex-wrap:wrap;gap:3px">${teams || '<span style="font-size:10px;color:#8b94b3">League not loaded</span>'}</div></div>
      <div class="mff-section"><h3>Format</h3>
        <select class="mff-select" id="mff-mode">${modeOptions()}</select></div>
      <button id="mff-sn-refresh" class="start-btn" style="background:#00ceb8;border:none;color:#0b1220;padding:8px;border-radius:4px;cursor:pointer;font-weight:700;text-transform:uppercase;letter-spacing:0.5px">Refresh league data</button>
      <div style="font-size:10px;color:#8b94b3">Players: ${state.players.length} · data ${esc(state.exportedAt)}${ver ? ' · v' + ver : ''}</div>`;
  }
  function seasonNoLeagueHTML() {
    const leagues = state.myLeagues.map((lg) => {
      const sc = lg.scoring_settings || {};
      const rec = sc.rec != null ? sc.rec : 1;
      const scLbl = rec === 1 ? 'PPR' : rec === 0.5 ? '½PPR' : rec === 0 ? 'STD' : rec + '/rec';
      const dyn = lg.settings && lg.settings.type >= 1 ? ' · dynasty' : '';
      return `<button data-snleague="${esc(lg.league_id)}" class="pos-filter" style="flex:1 1 100%;text-align:left;padding:6px 8px">
        <b>${esc(lg.name)}</b> <span style="color:#8b94b3">· ${lg.total_rosters} tm · ${scLbl}${dyn}</span></button>`;
    }).join('');
    return `
      <div id="mff-setup">
        <label>Season mode — pick your league</label>
        <div style="display:flex;gap:4px">
          <input type="text" id="mff-username" value="${esc(state.username)}" placeholder="Sleeper username"
            style="flex:1;background:#0b1220;border:1px solid #26304d;color:#eef1f9;padding:5px 8px;border-radius:4px;font-size:12px">
          <button id="mff-sn-leagues" style="background:#26304d;border:none;color:#eef1f9;padding:5px 10px;border-radius:4px;cursor:pointer;font-weight:600">FIND LEAGUES</button>
        </div>
        <div style="display:flex;flex-wrap:wrap;gap:3px">${leagues}</div>
        <div style="font-size:10px;color:#8b94b3">…or just open your league's page on sleeper.com</div>
        <div style="font-size:10px;color:#8b94b3">${esc(state.seasonStatus)}</div>
      </div>`;
  }
  // ---- TEAM tab: full-roster values under switchable sources (v0.15.0) ----
  // Same mode-aware SOURCES as draft mode (the league's detected format picks
  // the column): KTC value, Jack's rank, FantasyPros, Sleeper rank.
  const POS_ORDER = ['QB', 'RB', 'WR', 'TE', 'K', 'DST'];
  function seasonTeamHTML() {
    if (state.myLeagueRosterId == null) {
      return '<div style="font-size:11px;color:#8b94b3;padding:8px 2px">Pick your team on the SETTINGS tab first.</div>';
    }
    const srcId = SOURCES[state.seasonTeamSrc] ? state.seasonTeamSrc : 'ktc';
    const src = SOURCES[srcId];
    const chips = Object.entries(SOURCES).filter(([id]) => id !== 'jm').map(([id, s]) =>
      `<button class="pos-filter ${id === srcId ? 'active' : ''}" data-pksrc="${id}" style="flex:0 0 auto">${
        id === 'ktc' ? 'KTC' : id === 'jack' ? "JACK'S" : id === 'fp' ? 'FP' : 'SLPR'}</button>`).join('');
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
        const inj = state.slMeta[p.sid] && state.slMeta[p.sid].inj;
        return `<div style="display:flex;justify-content:space-between;align-items:baseline;padding:2px 2px;border-bottom:1px solid #1c2440;font-size:12px">
            <span style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:200px">${esc(p.n)}
              <span style="color:#8b94b3;font-size:10px">${esc(p.sTm || '')}${p.age ? ' · ' + p.age : ''}${inj ? ' · <span style="color:#d06d6d">' + inj + '</span>' : ''}</span></span>
            <span style="font-weight:600;color:${v == null ? '#8b94b3' : '#eef1f9'}">${
              v == null ? '—' : src.desc ? v.toLocaleString() : '#' + v}</span>
          </div>`;
      }).join('');
      return `<div style="display:flex;justify-content:space-between;font-size:10px;color:#8b94b3;text-transform:uppercase;letter-spacing:.5px;margin:8px 0 2px">
          <span class="pos pos-${pos.toLowerCase()}" style="padding:0 5px;border-radius:3px">${pos}</span>
          ${sub != null ? '<span>' + sub.toLocaleString() + '</span>' : ''}</div>${rows}`;
    }).join('');
    const total = srcId === 'ktc' ? mine.reduce((t, p) => t + (val(p) || 0), 0) : null;
    return `
      <div style="display:flex;gap:3px;flex-wrap:wrap;margin-bottom:4px">${chips}</div>
      ${total != null ? `<div style="display:flex;justify-content:space-between;font-size:12px;padding:2px;border-bottom:1px solid #26304d"><b>Team total (${esc(src.label)} ${state.mode.endsWith('_sf') ? 'SF' : '1QB'})</b><b style="color:#00ceb8">${total.toLocaleString()}</b></div>` : ''}
      ${groups}
      <div style="font-size:9px;color:#8b94b3;margin-top:6px">${esc(src.label)} in the league's detected format (${state.mode.replace('_', ' ').toUpperCase()}). Players outside the export show —.</div>`;
  }

  function seasonSimsHTML() {
    const ps = state.pickSim;
    if (ps.status === 'running') {
      return `<div style="padding:16px 6px;color:#8b94b3;font-size:12px">Running ${PK_SIMS.toLocaleString()} season sims…</div>`;
    }
    if (ps.status === 'idle') setTimeout(ensurePickSim, 0); // landed here via saved prefs
    const sf = pkSf();
    const dyn = pkDynasty();
    const note = ps.status === 'error'
      ? `<div style="background:#402a2a;color:#d06d6d;font-size:10px;padding:4px 6px;border-radius:4px;margin-bottom:6px">Sim unavailable (${esc(ps.note || 'unknown')})${dyn ? ' — showing generic KTC tier pick values' : ''}</div>` : '';
    const myRid = state.myLeagueRosterId;
    const nameById = {};
    state.seasonRosters.forEach((r) => { nameById[r.roster_id] = state.userNames[r.owner_id] || 'Team ' + r.roster_id; });
    // ---- projected standings (best first) + selected-team weekly drill-down ----
    const R = ps.results || {};
    const selRid = ps.selTeam != null ? ps.selTeam : myRid;
    const standOrder = state.seasonRosters.map((r) => r.roster_id)
      .sort((a, b) => {
        const ra = R[a], rb = R[b];
        if (!ra || !rb) return 0;
        return (rb.w - ra.w) || (rb.pf - ra.pf);
      });
    const pct1 = (v) => v == null ? '—' : Math.round(v * 100) + '%';
    const standRows = Object.keys(R).length ? standOrder.map((rid) => {
      const r = R[rid];
      if (!r) return '';
      const fin = pkExpFinish(+rid);
      const sel = +rid === selRid;
      return `<tr data-pkteam="${rid}" style="cursor:pointer;${+rid === myRid ? 'color:#00ceb8;' : ''}${sel ? 'background:#182138;' : ''}border-bottom:1px solid #1c2440">
          <td style="padding:2px 4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:95px">${sel ? '▸ ' : ''}${esc(nameById[rid] || rid)}</td>
          <td style="text-align:center;padding:2px 3px;white-space:nowrap">${r.w}-${r.l}</td>
          <td style="text-align:right;padding:2px 3px">${r.pf.toLocaleString()}</td>
          <td style="text-align:right;padding:2px 3px">${pct1(r.playoff)}</td>
          <td style="text-align:right;padding:2px 3px">${pct1(r.title)}</td>
          <td style="text-align:center;color:#8b94b3;padding:2px 3px;white-space:nowrap">${fin ? pkOrdinal(fin.mode) : '—'}</td>
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
        return `<tr style="border-bottom:1px solid #1c2440">
            <td style="padding:2px 4px;color:#8b94b3">W${wk}</td>
            <td style="padding:2px 4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:105px">${esc(nameById[w.opp] || w.opp)}</td>
            <td style="text-align:right;padding:2px 4px;color:${col};font-weight:600">${wp}%</td>
            <td style="text-align:right;padding:2px 4px">${w.pf.toFixed(1)}</td>
            <td style="text-align:right;padding:2px 4px;color:#8b94b3">${w.pa.toFixed(1)}</td>
          </tr>`;
      }).join('');
      weeklyHtml = `
        <div style="font-size:10px;color:#8b94b3;text-transform:uppercase;letter-spacing:.5px;margin:10px 0 3px">Week by week · ${esc(nameById[selRid] || selRid)}</div>
        <div style="font-size:10px;color:#8b94b3;margin-bottom:3px">Playoffs ${pct1(sel.playoff)}${sel.bye ? ' · Bye ' + pct1(sel.bye) : ''} · Finals ${pct1(sel.finals)} · Title ${pct1(sel.title)}</div>
        ${wkRows ? `<table style="width:100%;border-collapse:collapse;font-size:11px">
          <thead><tr style="color:#8b94b3;font-size:9px;text-transform:uppercase">
            <th style="text-align:left;padding:2px 4px">Wk</th><th style="text-align:left;padding:2px 4px">Opp</th>
            <th style="text-align:right;padding:2px 4px">Win</th><th style="text-align:right;padding:2px 4px">Proj</th>
            <th style="text-align:right;padding:2px 4px">Opp proj</th>
          </tr></thead><tbody>${wkRows}</tbody></table>` : '<div style="font-size:11px;color:#8b94b3;padding:2px">No remaining regular-season weeks.</div>'}`;
    }
    const standingsHtml = standRows ? `
      <div style="font-size:10px;color:#8b94b3;text-transform:uppercase;letter-spacing:.5px;margin:2px 0 3px">Projected standings <span style="text-transform:none">(tap a team)</span></div>
      <table style="width:100%;border-collapse:collapse;font-size:11px">
        <thead><tr style="color:#8b94b3;font-size:9px;text-transform:uppercase">
          <th style="text-align:left;padding:2px 4px">Team</th><th style="padding:2px 3px">Rec</th>
          <th style="text-align:right;padding:2px 3px">PF</th><th style="text-align:right;padding:2px 3px">PO</th>
          <th style="text-align:right;padding:2px 3px">Title</th><th style="padding:2px 3px">Fin</th>
        </tr></thead><tbody>${standRows}</tbody></table>${weeklyHtml}` : '';
    // ---- my picks ----
    const inv = (ps.inv && myRid != null && ps.inv[myRid]) || [];
    const myRows = inv.slice().sort((a, b) => (a.year - b.year) || (a.round - b.round)).map((pk) => {
      const rk = PK_ROUNDS[pk.round - 1];
      const v = tradePickValue(pk.year, pk.round, pk.orig); // handles >2028 extrapolation
      if (v == null) return '';
      const ex = pk.year > 2028; // extrapolated years: no mid-anchor delta, ~ marker
      const a = pkAnchors(Math.min(pk.year, 2028), rk, sf);
      const d = !ex && a && a.m ? Math.round(100 * (v - a.m) / a.m) : null;
      const via = pk.orig !== myRid ? ` <span style="color:#8b94b3;font-size:10px">via ${esc(nameById[pk.orig] || pk.orig)}</span>` : '';
      const dTxt = d == null ? '' : ` <span style="font-size:10px;color:${d >= 3 ? '#22c55e' : d <= -3 ? '#d06d6d' : '#8b94b3'}">${d >= 0 ? '+' : ''}${d}% vs mid</span>`;
      const fin = pk.orig !== myRid ? pkExpFinish(pk.orig) : null;
      const finTxt = fin ? `<div style="font-size:10px;color:#8b94b3;padding:0 2px 3px">${esc(nameById[pk.orig] || '')} proj ${pkOrdinal(fin.mode)} (${Math.round(fin.modeP * 100)}%)</div>` : '';
      return `<div style="display:flex;justify-content:space-between;align-items:baseline;padding:3px 2px;border-bottom:1px solid #1c2440;font-size:12px">
          <span>${pk.year} ${rk}${via}</span>
          <span><b style="color:#00ceb8">${ex ? '~' : ''}${v.toLocaleString()}</b>${dTxt}</span>
        </div>${finTxt}`;
    }).join('');
    // ---- league pick board (worst projected finish first = draft order) ----
    const order = state.seasonRosters.map((r) => r.roster_id).sort((a, b) => {
      const fa = pkExpFinish(a), fb = pkExpFinish(b);
      return (fb ? fb.ev : 0) - (fa ? fa.ev : 0);
    });
    const boardRows = order.map((rid) => {
      const fin = pkExpFinish(rid);
      const cells = [[2027, 1], [2027, 2], [2028, 1]].map(([y, rd]) => {
        const v = pkTeamPickValue(rid, y, PK_ROUNDS[rd - 1]);
        const owner = pkOwnerOf(y, rd, rid);
        const traded = owner != null && owner !== rid;
        return `<td style="text-align:right;padding:2px 4px;${traded ? 'color:#8b94b3' : ''}"${traded ? ` title="Traded to ${esc(nameById[owner] || owner)}"` : ''}>${v == null ? '—' : v.toLocaleString()}${traded ? '<span style="font-size:9px"> →</span>' : ''}</td>`;
      }).join('');
      return `<tr style="${rid === myRid ? 'color:#00ceb8;' : ''}border-bottom:1px solid #1c2440">
          <td style="padding:2px 4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:105px">${esc(nameById[rid] || rid)}</td>
          <td style="text-align:center;color:#8b94b3;padding:2px 4px;white-space:nowrap">${fin ? pkOrdinal(fin.mode) + ' <span style="font-size:9px">' + Math.round(fin.modeP * 100) + '%</span>' : '—'}</td>
          ${cells}</tr>`;
    }).join('');
    const statTxt = ps.status === 'done'
      ? PK_SIMS.toLocaleString() + ' sims' + (ps.synthPairs ? ' · synth schedule' : '')
        + (ps.tradedCount ? ' · ' + ps.tradedCount + ' traded picks applied' : '')
      : '';
    const picksHtml = !dyn ? '' : `
      <div style="font-size:10px;color:#8b94b3;text-transform:uppercase;letter-spacing:.5px;margin:${standingsHtml ? '12px' : '2px'} 0 3px">My picks · future drafts</div>
      ${myRows || `<div style="font-size:11px;color:#8b94b3;padding:4px 2px">${myRid == null ? 'Pick your team on the SETTINGS tab to see your pick inventory.' : 'No 2027/2028 picks — all dealt away.'}</div>`}
      <div style="font-size:10px;color:#8b94b3;text-transform:uppercase;letter-spacing:.5px;margin:10px 0 3px">League pick board</div>
      <table style="width:100%;border-collapse:collapse;font-size:11px">
        <thead><tr style="color:#8b94b3;font-size:9px;text-transform:uppercase">
          <th style="text-align:left;padding:2px 4px">Team</th><th style="padding:2px 4px">Proj fin</th>
          <th style="text-align:right;padding:2px 4px">'27 1st</th>
          <th style="text-align:right;padding:2px 4px">'27 2nd</th>
          <th style="text-align:right;padding:2px 4px">'28 1st</th>
        </tr></thead><tbody>${boardRows}</tbody></table>`;
    return `${note}${standingsHtml}${picksHtml}
      <div style="display:flex;align-items:center;gap:6px;margin-top:8px">
        <button id="mff-pk-rerun" style="background:#26304d;border:none;color:#eef1f9;padding:3px 8px;border-radius:4px;cursor:pointer;font-size:10px;font-weight:600">RE-RUN SIM</button>
        <span style="font-size:9px;color:#8b94b3">${statTxt}</span>
      </div>
      <div style="font-size:9px;color:#8b94b3;margin-top:6px;line-height:1.35">Standings/odds = ${PK_SIMS.toLocaleString()} Monte Carlo seasons (Clay projections × Vegas lines, league-scored, real matchups${ps.synthPairs ? ' — synth round-robin until Sleeper publishes them' : ''}). ${dyn ? `Pick values: draft order = inverse simmed standings; each pick's EV integrates the owner-of-record team's FULL finish distribution over the KTC ${sf ? 'Superflex' : '1QB'} Early/Mid/Late curve — collapse-tail risk earns extra credit (early slots are convex). 2028s regress 50% toward league average; ~2029s are extrapolated off the 2028 curve (KTC has no anchors there yet). ` : ''}Assumes rest-of-season rosters as-is; players without a Clay projection score 0 in the sim.</div>`;
  }

  function seasonHTML() {
    if (!state.seasonLeagueId) return seasonNoLeagueHTML();
    const tabs = [['lineup', 'LINEUP'], ['team', 'TEAM'], ['waivers', 'WAIVERS']]
      .concat(pkTabVisible() ? [['sims', 'SIMS']] : [])
      .concat([['snset', 'SETTINGS']]).map(([id, lbl]) =>
      `<button class="mff-tab ${state.seasonTab === id ? 'active' : ''}" data-sntab="${id}">${lbl}</button>`).join('');
    const content = state.seasonTab === 'waivers' ? seasonWaiversHTML()
      : state.seasonTab === 'team' ? seasonTeamHTML()
      : state.seasonTab === 'sims' && pkTabVisible() ? seasonSimsHTML()
      : state.seasonTab === 'snset' ? seasonSettingsHTML()
      : seasonLineupHTML();
    return `
      <div id="mff-tabs">${tabs}</div>
      ${content}
      <div id="mff-mode-line" style="display:flex;gap:6px;font-size:10px;color:#8b94b3;align-items:center">
        <span class="badge live" style="background:#2a4030;color:#6dd06d;padding:2px 6px;border-radius:3px;letter-spacing:0.5px;text-transform:uppercase;font-weight:600">SEASON</span>
        <span id="mff-status-line" style="flex:1">${esc(state.seasonStatus)}</span>
      </div>`;
  }

  function modeOptions() {
    let out = '';
    for (const [k, m] of Object.entries(MODES)) {
      out += `<option value="${k}" ${state.mode === k ? 'selected' : ''}>${m.label}${state.modeDetected === k ? ' ✓' : ''}</option>`;
    }
    return out;
  }

  function countsGridHTML() {
    const c = rosterCounts();
    const need = needPositions();
    const cells = ['QB', 'RB', 'WR', 'TE'].map((pos) =>
      `<div class="pos pos-${pos.toLowerCase()} ${need.has(pos) ? 'warn' : ''}">
        <span class="v">${c[pos]}</span><span class="l">${pos}</span>
      </div>`
    ).join('');
    return `<div id="mff-roster">${cells}</div>`;
  }

  function rosterListHTML() {
    let list = '';
    if (state.myRoster.length) {
      const byPos = {};
      for (const r of state.myRoster) (byPos[r.pos] = byPos[r.pos] || []).push(r);
      const ktcKey = state.mode.endsWith('1qb') ? 'ktc1qb' : 'ktcSf';
      const ktcLbl = state.mode.endsWith('1qb') ? '1QB' : 'SF';
      let totalKtc = 0;
      list = '<div class="mff-proj-roster" style="margin-top:4px">';
      for (const pos of ['QB', 'RB', 'WR', 'TE', 'K', 'DST', '?']) {
        const grp = byPos[pos];
        if (!grp) continue;
        list += grp.map((r) => {
          const ktc = r.p ? r.p[ktcKey] : null;
          if (ktc) totalKtc += ktc;
          const rm = r.manual
            ? `<button data-unmine="${esc(keyOf(r.p))}" title="Remove manual add" style="background:none;border:none;color:#d06d6d;cursor:pointer;font-size:10px;padding:0 2px">✕</button>`
            : '';
          return `<div class="mff-proj-roster-player">
            <span class="t">${esc(pos)}</span>
            <span class="n">${esc(r.name)}${r.manual ? ' <span style="color:#8b94b3;font-size:9px">(manual)</span>' : ''}</span>
            <span class="v">${ktc != null ? ktc : '—'}</span>${rm}
          </div>`;
        }).join('');
      }
      list += `<div class="mff-proj-roster-player" style="border-top:1px solid #26304d">
        <span class="t"></span><span class="n" style="color:#8b94b3">Total KTC (${ktcLbl})</span>
        <span class="v">${totalKtc}</span></div>`;
      const proj = starterProjPPG();
      if (proj > 0) {
        list += `<div class="mff-proj-roster-player">
          <span class="t"></span><span class="n" style="color:#8b94b3">Proj starters (${esc(state.scoringLabel)})</span>
          <span class="v">${proj} ppg</span></div>`;
      }
      list += '</div>';
    }
    if (!list) list = '<div class="mff-proj-empty">No picks yet</div>';
    return `<div class="mff-section">
      <h3>Players</h3>${list}
    </div>`;
  }

  function recsHTML() {
    const need = needPositions();
    const src = SOURCES[state.rankSource];
    const avail = sortedAvailable().slice(0, 60);
    if (!avail.length) return '<div class="mff-proj-empty">No players available</div>';
    // Tier separators only make sense while the list IS Jack's board order.
    const showTierSeps = state.rankSource === 'jack' && !state.sortVor && !!jackTierList();
    let lastTierLabel = null;
    return avail.map((p, i) => {
      const k = keyOf(p);
      const expanded = state.expandedKey === k;
      const v = src.get(p);
      const jm = p[modeKeys().jack] != null ? p[modeKeys().jack] : p.rank;
      const team = p.sTm || p.t || '';
      const adp = p[modeKeys().adp];
      const tag = adpTag(p);
      const stk = stackInfo(p);
      const tier = jackTierFor(p[modeKeys().jack]);
      let sep = '';
      if (showTierSeps && tier && tier.l !== lastTierLabel) {
        const c = jackTierColor(tier.l);
        sep = `<div class="mff-tier-sep" style="color:${c};border-color:${c}"><span class="mff-tier-sep-badge" style="background:${c}">${esc(tier.l)}</span>${esc(tier.n || 'TIER ' + tier.l)}</div>`;
        lastTierLabel = tier.l;
      }
      const corner = stk
        ? `<span class="mff-corner-badge"><span class="${stk.type === 'stack' ? 'stack-badge' : 'team-badge'}">${stk.type === 'stack' ? 'STACK' : 'TEAM'}</span></span>`
        : '';
      return `${sep}
      <div class="mff-rec ${i === 0 ? 'top' : ''} ${need.has(p.s) ? 'need' : ''} ${stk ? stk.type : ''}" data-key="${esc(k)}">
        ${corner}
        <div class="num">${i + 1}</div>
        <div class="info">
          <div class="name">${esc(p.n)}</div>
          <div class="meta">
            <span class="pos ${p.s}">${p.s}</span>
            <span>${esc(team)}</span>
            ${p.age != null ? `<span>${p.age}y</span>` : ''}
            <span>JM #${jm}${tier ? ` <b class="mff-jtier" style="color:${jackTierColor(tier.l)}" title="Jack's tier: ${esc(tier.n || tier.l)}">${esc(tier.l)}</b>` : ''}</span>
            ${state.mode.startsWith('dyn') && p.jmS != null ? `<span style="color:${esc(p.jmCol || '#8b94b3')}" title="JM prospect model score${p.jmT ? ' · ' + esc(p.jmT) : ''}${p.jmC ? ' · class of ' + p.jmC : ''}">JM ${p.jmS}</span>` : ''}
            ${adp != null ? `<span>ADP ${adp}</span>` : ''}
            ${p.pPg != null ? `<span>${p.pPg}ppg</span>` : ''}
          </div>
          ${tag ? `<div class="why"><span class="tag ${tag}">${tag}</span></div>` : ''}
        </div>
        <div class="score">${fmtVal(v)}</div>
        ${expanded ? profileHTML(p, k) : ''}
      </div>`;
    }).join('');
  }

  // Site consensus weekly numbers (Sleeper h/p/s, ESPN/FP [half,ppr,std]) in
  // the league's rec-scoring bucket. Only for the week the feed was pulled for.
  function wkConsensusRow(p) {
    const c = state.wkConsensus || (MOCK && MOCK.consensus) || null;
    if (!c || !c.players || c.week !== state.seasonWeek) return '';
    let row = c.players[p.n];
    if (!row) {
      if (!state.wkConsensusIdx) {
        const idx = Object.create(null);
        for (const n of Object.keys(c.players)) idx[norm(n)] = c.players[n];
        state.wkConsensusIdx = idx;
      }
      row = state.wkConsensusIdx[norm(p.n)];
    }
    if (!row) return '';
    const recPts = state.scoringVals && state.scoringVals.recPts != null ? state.scoringVals.recPts : 1;
    const fi = recPts >= 0.75 ? 1 : recPts >= 0.25 ? 0 : 2; // [half, ppr, std]
    const slp = fi === 1 ? row.p : fi === 0 ? row.h : row.s;
    const parts = [];
    if (typeof slp === 'number') parts.push('SLP ' + slp.toFixed(1));
    if (row.e && typeof row.e[fi] === 'number') parts.push('ESPN ' + row.e[fi].toFixed(1));
    if (row.f && typeof row.f[fi] === 'number') parts.push('FP ' + row.f[fi].toFixed(1));
    if (!parts.length) return '';
    return `<div class="prof-row"><span class="k" title="Site consensus weekly projections (Sleeper / ESPN / FantasyPros), ${fi === 1 ? 'PPR' : fi === 0 ? 'half-PPR' : 'standard'} — reference only, not the sim number">Wk ${c.week} sources</span><span class="v">${esc(parts.join(' · '))}</span></div>`;
  }

  // K/DST full-season weekly projection strip (mirrors the site card's strip):
  // all 18 weeks scored with the league-scored Vegas models above against each
  // week's line from the site schedule map. Colored by matchup delta vs the
  // neutral-implied baseline; W15-17 carry the playoff border. Pure model —
  // no injury/actuals decay (it's a planning strip, not a lineup verdict).
  function kdstWeekStripHTML(p) {
    if ((p.s !== 'K' && p.s !== 'DST') || !p.sTm) return '';
    const sched = state.schedule[p.sTm];
    if (!sched || !Object.keys(sched).length) return '';
    const base = p.s === 'K' ? kickerProjFor(p, null) : dstProjFor(p, null);
    if (base == null || !isFinite(base)) return '';
    let cells = '';
    for (let wk = 1; wk <= 18; wk++) {
      const g = sched[wk];
      const border = (wk >= 15 && wk <= 17)
        ? 'border:1px solid rgba(224,160,96,.55);' : 'border:1px solid #26304d;';
      if (!g) {
        const isBye = p.bye != null && +p.bye === wk;
        cells += `<div style="flex:0 0 44px;text-align:center;padding:3px 1px;border-radius:4px;background:#141a2e;${border}${isBye ? '' : 'opacity:.5;'}" title="${isBye ? 'Bye week' : 'W' + wk + ' — line not posted yet'}">` +
          `<div style="font-size:8px;color:#8b94b3">W${wk}</div>` +
          `<div style="font-size:10px;font-weight:700;color:#8b94b3;padding:3px 0 2px">${isBye ? 'BYE' : '—'}</div></div>`;
        continue;
      }
      const v = p.s === 'K' ? kickerProjFor(p, g) : dstProjFor(p, g);
      const delta = v - base;
      const clr = delta >= 0.4 ? '#6dd06d' : delta >= 0.15 ? '#9ed08f'
        : delta <= -0.4 ? '#d06d6d' : delta <= -0.15 ? '#e0a060' : '#cbd2e6';
      const oppTxt = (g.home ? 'vs' : '@') + g.opp;
      const imp = p.s === 'DST'
        ? (g.total != null && g.implied != null ? g.total - g.implied : null)
        : g.implied;
      const tip = 'W' + wk + ' ' + oppTxt +
        (imp != null ? ' · ' + (p.s === 'DST' ? 'opp implied ' : 'implied ') + (Math.round(imp * 10) / 10) : '') +
        (g.total != null ? ' · O/U ' + g.total : '') +
        ' · ' + (delta >= 0 ? '+' : '') + delta.toFixed(1) + ' vs ' + base.toFixed(1) + ' baseline (league scoring)';
      cells += `<div style="flex:0 0 44px;text-align:center;padding:3px 1px;border-radius:4px;background:#141a2e;cursor:help;${border}" title="${esc(tip)}">` +
        `<div style="font-size:8px;color:#8b94b3">W${wk}</div>` +
        `<div style="font-size:12px;font-weight:800;line-height:1.15;color:${clr}">${v.toFixed(1)}</div>` +
        `<div style="font-size:7.5px;color:#8b94b3;white-space:nowrap">${esc(oppTxt)}${imp != null ? '·' + Math.round(imp) : ''}</div></div>`;
    }
    return `<div class="prof-row" style="display:block">` +
      `<span class="k" style="display:block;margin-bottom:3px">WEEKLY PROJ <span style="color:#8b94b3;font-weight:400">· Vegas model, league scoring · amber = W15-17</span></span>` +
      `<div style="display:flex;gap:3px;overflow-x:auto;padding-bottom:3px">${cells}</div></div>`;
  }

  function profileHTML(p, k) {
    const mk = modeKeys();
    const modeLbl = MODES[state.mode].label;
    const sfMode = state.mode.endsWith('_sf');
    const stk = stackInfo(p);
    const rows = [
      ['KTC Superflex', p.ktcSf], ['KTC 1QB', p.ktc1qb],
      ['JM Score' + (p.jmC ? " ('" + String(p.jmC).slice(2) + ' class)' : ''),
        p.jmS != null ? p.jmS + (p.jmT ? ' · ' + p.jmT : '') : null],
      ["Jack " + modeLbl, p[mk.jack] == null ? null
        : '#' + p[mk.jack] + (() => { const t = jackTierFor(p[mk.jack]); return t ? ' · ' + (t.n || 'Tier ' + t.l) : ''; })()],
      ["Jack Redraft", mk.jack !== 'rank' && p.rank != null ? '#' + p.rank : null],
      ['FP ' + modeLbl, p[mk.fp] == null ? null : '#' + p[mk.fp]],
      ['Sleeper ' + modeLbl, p[mk.sl] == null ? null : '#' + p[mk.sl]],
      ['ADP ' + modeLbl, p[mk.adp]],
      ['Proj PPG (Clay, ' + state.scoringLabel + ')', p.pPg],
      ['Proj Season', p.szn],
      ['Ceiling PPG', p.cPpg],
      ['VOR' + (sfMode ? ' (SF)' : ''), p[mk.vor]],
      ['Upside' + (sfMode ? ' (SF)' : ''), p[mk.up]],
      ['Age', p.age], ["'25 PPG", p.p25],
      ['Bye', p.bye], ['Team', p.sTm || p.t],
    ].filter((r) => r[1] != null)
      .map((r) => `<div class="prof-row"><span class="k">${r[0]}</span><span class="v">${esc(r[1])}</span></div>`)
      .join('');
    const stackRow = stk
      ? `<div class="prof-row stack"><span class="k">${stk.type === 'stack' ? 'STACKS WITH' : 'SAME TEAM'}</span><span class="v">${esc(stk.names.join(', '))}</span></div>`
      : '';
    // Playoff SOS pills (weeks 15-17) from the shared MFF site dataset
    let sosRow = '';
    const sosData = window.MFF_PLAYOFF_SOS;
    const sos = sosData && p.sTm && sosData[p.sTm] && sosData[p.sTm][p.s];
    if (sos) {
      const pills = ['15', '16', '17'].map((w) => {
        const m = sos[w];
        if (!m) return '';
        return `<span style="background:${esc(m.color)};color:#0b1220;border-radius:3px;padding:1px 5px;font-size:9px;font-weight:700" title="SOS rank ${m.rank}/32 · implied ${m.impliedTotal} pts">W${w} ${m.home ? 'vs' : '@'}${esc(m.opp)}</span>`;
      }).join('');
      sosRow = `<div class="prof-row"><span class="k">Playoff SOS</span><span class="v" style="display:flex;gap:3px;flex-wrap:wrap">${pills}</span></div>`;
    }
    const markBtn = state.appMode === 'draft'
      ? `<button data-markdrafted="${esc(k)}" style="background:#402a2a;border:none;color:#d06d6d;padding:5px;border-radius:4px;cursor:pointer;font-weight:600;font-size:10px;margin-top:4px">MARK DRAFTED (manual)</button>`
      : '';
    return `<div class="mff-profile" style="pointer-events:auto">${rows}${wkConsensusRow(p)}${sosRow}${stackRow}${kdstWeekStripHTML(p)}${markBtn}</div>`;
  }

  function pickAssetsHTML() {
    if (!state.pickAssets.length) return '<div class="mff-proj-empty">No pick values exported</div>';
    return '<div class="mff-proj-info">KTC rookie-pick values (reference — not auto-tracked)</div>' +
      state.pickAssets
        .filter((pa) => !state.manualDrafted.has('PICK|' + pa.n))
        .map((pa) => `
        <div class="mff-rec" data-pickasset="${esc(pa.n)}">
          <div class="num">PK</div>
          <div class="info"><div class="name">${esc(pa.n)}</div>
            <div class="meta"><span>1QB: ${fmtVal(pa.ktc1qb)}</span></div></div>
          <div class="score">${fmtVal(pa.ktcSf)}</div>
        </div>`).join('');
  }

  function searchSuggestionsHTML() {
    const q = norm(state.searchQ);
    if (!q || q.length < 2) return '';
    const hits = state.players.filter((p) => norm(p.n).includes(q)).slice(0, 8);
    if (!hits.length) return '<div class="s"><span style="color:#8b94b3">No matches</span></div>';
    return hits.map((p) => {
      const k = keyOf(p);
      const gone = isDrafted(p);
      const btns = gone
        ? '<span class="pos">drafted</span>'
        : `<button data-msearch="${esc(k)}" data-act="drafted" title="Mark drafted (someone else)" style="background:#402a2a;border:none;color:#d06d6d;border-radius:3px;cursor:pointer;font-size:10px;padding:1px 6px">✕</button>
           <button data-msearch="${esc(k)}" data-act="mine" title="Add to MY roster" style="background:#2a4030;border:none;color:#6dd06d;border-radius:3px;cursor:pointer;font-size:10px;padding:1px 6px;margin-left:3px">＋</button>`;
      return `<div class="s"><span>${esc(p.n)} <span class="pos">${p.s} ${esc(p.sTm || '')}</span></span><span>${btns}</span></div>`;
    }).join('');
  }

  // ---------- events ----------
  function onBodyClick(e) {
    // ---- season-mode controls ----
    const snTab = e.target.closest('[data-sntab]');
    if (snTab) {
      state.seasonTab = snTab.dataset.sntab;
      saveSeasonPrefs();
      if (state.seasonTab === 'sims') setTimeout(ensurePickSim, 0);
      render();
      return;
    }
    const pkTeam = e.target.closest('[data-pkteam]');
    if (pkTeam) {
      state.pickSim.selTeam = +pkTeam.dataset.pkteam;
      render();
      return;
    }
    const pkSrc = e.target.closest('[data-pksrc]');
    if (pkSrc) {
      state.seasonTeamSrc = pkSrc.dataset.pksrc;
      saveSeasonPrefs();
      render();
      return;
    }
    if (e.target.id === 'mff-pk-rerun') {
      const lid = state.seasonLeagueId;
      if (lid) store.set({ ['sleeperPickSim_' + lid]: null, ['sleeperPairs_' + lid]: null });
      Object.assign(state.pickSim, { status: 'idle', placeCounts: null, recHash: null });
      ensurePickSim();
      return;
    }
    const snPos = e.target.closest('[data-snpos]');
    if (snPos) {
      state.seasonPosFilter = snPos.dataset.snpos;
      saveSeasonPrefs();
      render();
      return;
    }
    const snLeague = e.target.closest('[data-snleague]');
    if (snLeague) {
      state.appMode = 'season';
      initForLeague(snLeague.dataset.snleague);
      return;
    }
    const snRoster = e.target.closest('[data-snroster]');
    if (snRoster) {
      state.myLeagueRosterId = parseInt(snRoster.dataset.snroster, 10);
      saveSeasonPrefs();
      render();
      return;
    }
    if (e.target.id === 'mff-sn-find') {
      const input = root.querySelector('#mff-username');
      if (input) state.username = input.value.trim();
      store.set({ 'sleeperHelper.username': state.username });
      state.myUserId = null; // re-resolve for the (possibly new) username
      findSeasonTeam().then((found) => {
        state.seasonStatus = found ? 'Team found — you are ' + (state.userNames[state.myUserId] || state.username)
          : 'No team for that username here — tap yours below';
        render();
      });
      return;
    }
    if (e.target.id === 'mff-sn-leagues') {
      const input = root.querySelector('#mff-username');
      if (input) state.username = input.value.trim();
      store.set({ 'sleeperHelper.username': state.username });
      state.myUserId = null;
      loadMyLeagues();
      return;
    }
    if (e.target.id === 'mff-sn-refresh') {
      state.seasonStatus = 'Refreshing…';
      renderStatusOnly();
      Promise.all([refreshLeagueData(), fetchTrending()]).then(() => render());
      return;
    }
    // ---- draft-mode controls ----
    const slotBtn = e.target.closest('[data-slot]');
    if (slotBtn) {
      state.mySlot = parseInt(slotBtn.dataset.slot, 10);
      state.myUserId = null; // manual slot overrides username attribution
      render();
      return;
    }
    if (e.target.id === 'mff-find-slot') { findSlot(); return; }
    if (e.target.id === 'mff-start') { startTracking(); return; }
    if (e.target.id === 'mff-sort-vor') {
      state.sortVor = !state.sortVor;
      saveDraftPrefs();
      render();
      return;
    }
    const tab = e.target.closest('[data-tab]');
    if (tab) {
      state.tab = tab.dataset.tab;
      render();
      return;
    }
    const mark = e.target.closest('[data-markdrafted]');
    if (mark) {
      state.manualDrafted.add(mark.dataset.markdrafted);
      state.expandedKey = null;
      saveDraftPrefs();
      render();
      return;
    }
    const ms = e.target.closest('[data-msearch]');
    if (ms) {
      const key = ms.dataset.msearch;
      if (ms.dataset.act === 'mine') state.manualMine.add(key);
      else state.manualDrafted.add(key);
      state.searchQ = '';
      processPicks(state.picks);
      saveDraftPrefs();
      render();
      return;
    }
    const um = e.target.closest('[data-unmine]');
    if (um) {
      state.manualMine.delete(um.dataset.unmine);
      processPicks(state.picks);
      saveDraftPrefs();
      render();
      return;
    }
    const pa = e.target.closest('[data-pickasset]');
    if (pa) {
      state.manualDrafted.add('PICK|' + pa.dataset.pickasset);
      saveDraftPrefs();
      render();
      return;
    }
    const chip = e.target.closest('[data-pos]');
    if (chip) {
      state.posFilter = chip.dataset.pos;
      saveDraftPrefs();
      render();
      return;
    }
    const rec = e.target.closest('.mff-rec[data-key]');
    if (rec) {
      const k = rec.dataset.key;
      state.expandedKey = state.expandedKey === k ? null : k;
      render();
    }
  }
  function onBodyChange(e) {
    if (e.target.id === 'mff-mode') {
      applyMode(e.target.value, true);
      saveDraftPrefs();
      render();
      return;
    }
    if (e.target.id === 'mff-rank-source') {
      state.rankSource = e.target.value;
      saveDraftPrefs();
      render();
    }
    if (e.target.id === 'mff-username') {
      state.username = e.target.value.trim();
      store.set({ 'sleeperHelper.username': state.username });
    }
    if (e.target.id === 'mff-notify') {
      state.notify = e.target.checked;
      saveDraftPrefs();
    }
  }
  function onBodyInput(e) {
    if (e.target.id !== 'mff-search') return;
    state.searchQ = e.target.value;
    const sug = root.querySelector('#mff-suggestions');
    if (sug) {
      sug.style.display = state.searchQ.trim().length >= 2 ? '' : 'none';
      sug.innerHTML = searchSuggestionsHTML();
    }
  }

  async function findSlot() {
    const input = root.querySelector('#mff-username');
    state.username = (input ? input.value : state.username).trim();
    if (!state.username) return;
    store.set({ 'sleeperHelper.username': state.username });
    state.statusMsg = 'Looking up ' + state.username + '…';
    render();
    try {
      const user = await api('/user/' + encodeURIComponent(state.username));
      if (!user || !user.user_id) throw new Error('user not found');
      state.myUserId = user.user_id;
      const order = state.draft && state.draft.draft_order;
      const slot = order ? order[user.user_id] : null;
      if (slot) {
        state.mySlot = slot;
        state.statusMsg = 'You are slot ' + slot;
      } else {
        state.statusMsg = 'User found — not in this draft order yet; pick a slot';
      }
    } catch (e) {
      state.statusMsg = 'Lookup failed: ' + e.message;
    }
    render();
  }

  function startTracking() {
    if (!state.mySlot || !state.draftId) return;
    state.tracking = true;
    state.tab = 'draft';
    saveDraftPrefs();
    startPolling();
    // wake the background slow-draft watcher
    try { chrome.runtime.sendMessage({ type: 'mffWatch', draftId: state.draftId }, () => chrome.runtime.lastError); } catch (e) {}
    render();
  }

  function saveDraftPrefs() {
    if (!state.draftId) return;
    const d = state.draft;
    store.set({
      ['sleeperDraft_' + state.draftId]: {
        slot: state.mySlot,
        userId: state.myUserId,
        rankSource: state.rankSource,
        mode: state.mode,
        modeManual: state.modeManual,
        posFilter: state.posFilter,
        sortVor: state.sortVor,
        notify: state.notify,
        // snapshot for the background slow-draft watcher
        meta: d && d.settings ? {
          teams: d.settings.teams,
          rounds: d.settings.rounds,
          reversal_round: d.settings.reversal_round || 0,
          type: d.type,
          name: (d.metadata && d.metadata.name) || '',
        } : null,
        manualDrafted: [...state.manualDrafted],
        manualMine: [...state.manualMine],
        tracking: state.tracking,
      },
    });
  }

  // ---------- on-page chips in Sleeper's own player list ----------
  // Mirrors the UD extension's page decoration. Sleeper's list rows are
  // .player-rank-item2 (virtualized — rows recycle on scroll), with the pure
  // player name as the first text node inside .name-wrapper. Re-runs on an
  // interval; skips rows whose chip is already current to avoid flicker.
  let decorateTimer = null;
  const TAG_COLORS = {
    STEAL: ['#2a4030', '#6dd06d'], Value: ['#2a3a40', '#6dc0d0'],
    Reach: ['#402a2a', '#d06d6d'], Stretch: ['#4a3f30', '#ffc99b'],
  };
  function clearRowStyle(row) {
    row.style.removeProperty('background');
    row.style.removeProperty('box-shadow');
    row.style.removeProperty('outline');
    row.style.removeProperty('outline-offset');
  }
  function pillHTML(text, bg, fg, title) {
    return `<span ${title ? 'title="' + esc(title) + '"' : ''} style="background:${bg};color:${fg};` +
      'font-size:8px;font-weight:700;border-radius:3px;padding:0 3px;line-height:13px;' +
      'white-space:nowrap;flex:0 0 auto">' + esc(text) + '</span>';
  }
  function lastName(n) {
    const parts = String(n || '').replace(/ D\/ST$/, '').split(' ');
    return (parts[parts.length - 1] || '').toUpperCase();
  }
  function decoratePlayerList() {
    if (!state.players.length) return;
    const rows = document.querySelectorAll('.player-rank-item2');
    if (!rows.length) return;
    const need = needPositions();
    const sosData = window.MFF_PLAYOFF_SOS;
    for (const row of rows) {
      const nw = row.querySelector('.name-wrapper');
      if (!nw) continue;
      let nameTxt = '';
      for (const n of nw.childNodes) {
        if (n.nodeType === 3 && n.textContent.trim()) { nameTxt = n.textContent.trim(); break; }
      }
      const clearRowDecor = () => {
        row.querySelectorAll('.mff-page-chip, .mff-corner, .mff-rank-pills').forEach((el) => el.remove());
        delete row.dataset.mffSig;
        clearRowStyle(row);
      };
      if (!nameTxt) { clearRowDecor(); continue; }
      const posM = row.className.match(/\b(QB|RB|WR|TE|K|DEF)\b/);
      const pos = posM ? (posM[1] === 'DEF' ? 'DST' : posM[1]) : '';
      const p = findPlayer(nameTxt, pos);
      if (!p) { clearRowDecor(); continue; }

      // Whole-row highlight, Underdog-card look: green OUTLINE around the row
      // for STACK (like UD's stacked cards), slate outline for same TEAM,
      // cyan inset edge for positional NEED.
      const stk = stackInfo(p);
      if (stk && stk.type === 'stack') {
        row.style.setProperty('background', 'rgba(88, 167, 255, 0.10)', 'important');
        row.style.setProperty('outline', '1px solid #58a7ff', 'important');
        row.style.setProperty('outline-offset', '-1px', 'important');
        row.style.removeProperty('box-shadow');
      } else if (stk && stk.type === 'team') {
        row.style.setProperty('background', 'rgba(148, 163, 184, 0.08)', 'important');
        row.style.setProperty('outline', '1px solid rgba(148, 163, 184, 0.55)', 'important');
        row.style.setProperty('outline-offset', '-1px', 'important');
        row.style.removeProperty('box-shadow');
      } else if (need.has(p.s)) {
        row.style.removeProperty('background');
        row.style.removeProperty('outline');
        row.style.removeProperty('outline-offset');
        row.style.setProperty('box-shadow', 'inset 3px 0 0 #6dc0d0', 'important');
      } else {
        clearRowStyle(row);
      }

      // Two injection points per row (all one-line, fixed-height safe):
      //  - top-right of the name cell: ★ STACK <QB> + $$/$ value badge
      //  - under the name: playoff pills WITH opponents (15 @PIT …)
      // (RK-cell rank/tier/KTC/JM pills removed 0.29.1 — Jack: cluttered the
      // board; ranks still live in the sidebar list.)
      const tag = adpTag(p);
      const sos = sosData && p.sTm && sosData[p.sTm] && sosData[p.sTm][p.s];

      let cornerInner = '';
      if (stk && stk.type === 'stack') {
        cornerInner += pillHTML('★ ' + lastName(stk.names[0]), '#1e3a5f', '#58a7ff', 'STACK with ' + stk.names.join(', '));
      }
      if (tag === 'STEAL') cornerInner += pillHTML('$$', TAG_COLORS.STEAL[0], TAG_COLORS.STEAL[1], 'STEAL — 2+ rounds past ADP');
      else if (tag === 'Value') cornerInner += pillHTML('$', TAG_COLORS.Value[0], TAG_COLORS.Value[1], 'VALUE — a round past ADP');

      let sosInner = '';
      if (sos) {
        for (const w of ['15', '16', '17']) {
          const m = sos[w];
          if (!m) continue;
          sosInner += pillHTML(w + ' ' + (m.home ? 'vs' : '@') + m.opp, m.color, '#0b1220',
            'Week ' + w + ' playoff matchup · SOS rank ' + m.rank + '/32 · implied ' + m.impliedTotal + ' pts');
        }
      }

      const sig = cornerInner + '||' + sosInner;
      if (row.dataset.mffSig === sig) continue;
      row.dataset.mffSig = sig;
      // .mff-rank-pills stays in the removal selectors so pills injected by a
      // pre-0.29.1 build get cleaned up when the extension reloads mid-page.
      row.querySelectorAll('.mff-page-chip, .mff-corner, .mff-rank-pills').forEach((el) => el.remove());

      // ★ STACK + value badge sit NEXT TO the name, anchored to the name
      // text's own measured line (anchoring to the cell top clips — Sleeper
      // vertically centers the name block in a fixed-height row).
      let lineInner = sosInner;
      const nameCell = row.querySelector('.name') || nw.parentElement;
      const nameTn = [...nw.childNodes].find((n) => n.nodeType === 3 && n.textContent.trim());
      if (cornerInner && nameCell && nameTn) {
        if (getComputedStyle(nameCell).position === 'static') nameCell.style.position = 'relative';
        const rg = document.createRange();
        rg.selectNodeContents(nameTn);
        const ntr = rg.getBoundingClientRect();
        const cellR = nameCell.getBoundingClientRect();
        const leftPx = Math.round(ntr.right - cellR.left) + 5;
        const topPx = Math.round(ntr.top - cellR.top + (ntr.height - 13) / 2);
        const cb = document.createElement('span');
        cb.className = 'mff-corner';
        cb.innerHTML = cornerInner;
        cb.style.cssText = 'position:absolute;left:' + leftPx + 'px;top:' + topPx + 'px;height:13px;' +
          'display:flex;gap:2px;z-index:3;max-width:calc(100% - ' + (leftPx + 4) + 'px);overflow:hidden;';
        nameCell.appendChild(cb);
      } else if (cornerInner) {
        lineInner = cornerInner + sosInner; // fallback: lead the pill line
      }
      if (lineInner) {
        const chip = document.createElement('span');
        chip.className = 'mff-page-chip';
        chip.innerHTML = lineInner;
        chip.style.cssText =
          'display:flex;flex-wrap:nowrap;gap:2px;margin-top:1px;max-width:100%;height:13px;' +
          'overflow:hidden;position:relative;z-index:2;align-self:flex-start;';
        nw.appendChild(chip);
      }
    }
  }
  // Roster panel (right side): inline SOS pills with opponents on the .team
  // line — "15 @KC 16 vsNO 17 vsLV" like the UD roster view — plus a green
  // outline + ★ on MY rostered players that stack with each other.
  function decorateRosterPanel() {
    const rows = document.querySelectorAll('.draft-roster-list-item');
    if (!rows.length) return;
    const sosData = window.MFF_PLAYOFF_SOS;
    for (const row of rows) {
      const meta = row.querySelector('.meta-container');
      const nameEl = meta && meta.querySelector('.name');
      const teamEl = meta && meta.querySelector('.team');
      if (!nameEl || !teamEl) continue;
      const nameTxt = nameEl.textContent.trim();
      const posTok = (teamEl.textContent.trim().match(/^(QB|RB|WR|TE|K|DEF|DST)/) || [])[1] || '';
      const pos = posTok === 'DEF' ? 'DST' : posTok;
      const p = findPlayer(nameTxt, pos);
      const existing = teamEl.querySelector('.mff-roster-pills');
      if (!p) {
        if (existing) existing.remove();
        clearRowStyle(row);
        continue;
      }
      // ★/outline only for MY players (the panel can show other teams too;
      // their players shouldn't light up against my roster).
      const isMine = state.myRoster.some((r) => r.p === p);
      const mates = state.myRoster.filter((r) => r.p && r.p !== p && r.p.sTm === p.sTm);
      const isStack = isMine && (
        ((p.s === 'WR' || p.s === 'TE') && mates.some((r) => r.pos === 'QB')) ||
        (p.s === 'QB' && mates.some((r) => r.pos === 'WR' || r.pos === 'TE')));
      if (isStack) {
        row.style.setProperty('outline', '1px solid #58a7ff', 'important');
        row.style.setProperty('outline-offset', '-1px', 'important');
        row.style.setProperty('background', 'rgba(88, 167, 255, 0.08)', 'important');
      } else {
        clearRowStyle(row);
      }
      const pills = [];
      if (isStack) {
        pills.push(pillHTML('★', '#1e3a5f', '#58a7ff', 'STACK with ' + mates.map((m) => m.name).join(', ')));
      }
      if (p.pPg != null) {
        pills.push(pillHTML(p.pPg + 'ppg', '#26304d', '#00ceb8', 'Clay projection: ' + p.pPg + ' PPG (' + state.scoringLabel + ')' + (p.szn != null ? ' · ' + p.szn + ' season pts' : '')));
      }
      const sos = sosData && p.sTm && sosData[p.sTm] && sosData[p.sTm][p.s];
      if (sos) {
        for (const w of ['15', '16', '17']) {
          const m = sos[w];
          if (!m) continue;
          pills.push(pillHTML(w + ' ' + (m.home ? 'vs' : '@') + m.opp, m.color, '#0b1220',
            'Week ' + w + ' playoff matchup · SOS rank ' + m.rank + '/32 · implied ' + m.impliedTotal + ' pts'));
        }
      }
      const inner = pills.join('');
      if (existing && existing.dataset.mffSig === inner) continue;
      if (existing) existing.remove();
      if (!inner) continue;
      const span = document.createElement('span');
      span.className = 'mff-roster-pills';
      span.dataset.mffSig = inner;
      span.innerHTML = inner;
      span.style.cssText =
        'display:inline-flex;flex-wrap:nowrap;gap:2px;margin-left:5px;overflow:hidden;' +
        'vertical-align:middle;position:relative;z-index:2;';
      teamEl.appendChild(span);
    }
  }

  // ---------- season decoration: league TEAM page ----------
  // sleeper.com/leagues/<id>/team rows are .team-roster-item >
  // .cell-player-meta > .player-name-row > [abbrev name ("L Jackson"),
  // "POS - TM", "(bye)"]. Free agents show "POS -" (no team); DST rows show
  // the team abbr as the name; trailing empty roster slots have no name-row.
  // Names are abbreviated → match first initial + last name + pos (+ team),
  // my roster first, then the full pool.
  function matchAbbrevPlayer(nm, pos, team) {
    if (pos === 'DST') {
      const abbr = team || nm;
      return state.players.find((x) => x.s === 'DST' && x.sTm === abbr) || null;
    }
    const parts = nm.split(/\s+/);
    if (parts.length < 2) return null;
    const init = (parts[0][0] || '').toLowerCase();
    const last = norm(parts.slice(1).join(' '));
    const hit = (list, useTeam) => list.find((x) => {
      if (x.s !== pos) return false;
      if (useTeam && team && x.sTm !== team) return false;
      const n = norm(x.n);
      return n[0] === init && (n === init + ' ' + last || n.endsWith(' ' + last));
    });
    const mine = myPlayerObjs().filter((x) => !x._unmatched);
    return hit(mine, true) || hit(mine, false) || hit(state.players, true) || hit(state.players, false) || null;
  }
  // Find the row's native game line (a leaf element like "Sun 1:00 PM @ IND"
  // outside the name row) and color it by matchup quality. Text-only tint —
  // Sleeper's dark theme carries the pill greens/reds fine; 'mid' just gets
  // the tooltip so the colored lines stay meaningful.
  function clearOppTint(el) {
    el.classList.remove('mff-opp-hl');
    el.removeAttribute('title');
    el.style.removeProperty('color');
    el.style.fontWeight = '';
    delete el.dataset.mffOppSig;
  }
  function tintGameLine(row, nameRow, g) {
    let el = null;
    for (const cand of row.querySelectorAll('div,span,p')) {
      if (cand.children.length || nameRow.contains(cand) || cand.closest('.mff-tr-pills')) continue;
      const t = (cand.textContent || '').trim();
      if (t && t.length <= 40 && /(^|\s)(vs|@)\s?[A-Z]{2,4}\b/.test(t)) { el = cand; break; }
    }
    if (!el) return null;
    const sig = g.cls + '|' + g.tip;
    if (el.dataset.mffOppSig !== sig) {
      el.dataset.mffOppSig = sig;
      el.classList.add('mff-opp-hl');
      el.title = g.tip;
      const col = g.cls === 'good' ? '#6dd06d' : g.cls === 'bad' ? '#d06d6d' : '';
      el.style.setProperty('color', col, col ? 'important' : '');
      el.style.fontWeight = col ? '600' : '';
    }
    return el;
  }
  function decorateTeamPage() {
    if (state.appMode !== 'season' || !state.seasonLeague) return;
    const rows = document.querySelectorAll('.team-roster-item');
    if (!rows.length) return;
    const calc = seasonLineupCalc();
    for (const row of rows) {
      const clearIt = () => {
        const ex = row.querySelector('.mff-tr-pills');
        if (ex) ex.remove();
        row.querySelectorAll('.mff-opp-hl').forEach(clearOppTint);
        clearRowStyle(row);
        delete row.dataset.mffSig;
      };
      const nameRow = row.querySelector('.cell-player-meta .player-name-row');
      if (!nameRow) { if (row.dataset.mffSig) clearIt(); continue; }
      const kids = nameRow.children;
      const nm = kids[0] ? kids[0].textContent.trim() : '';
      const posTeam = kids[1] ? kids[1].textContent.trim() : '';
      const pm = posTeam.match(/^(QB|RB|WR|TE|K|DEF|DST)(?:\s*-\s*([A-Z]{2,4}))?/);
      if (!nm || !pm) { clearIt(); continue; }
      const p = matchAbbrevPlayer(nm, pm[1] === 'DEF' ? 'DST' : pm[1], pm[2] || null);
      if (!p) { clearIt(); continue; }
      const verdict = calc ? calc.cls[keyOf(p)] : null;
      const pills = [];
      if (verdict === 'go') pills.push(pillHTML('▲ START', '#2a4030', '#6dd06d', 'Projects better than a current starter — put him in'));
      else if (verdict === 'sit') pills.push(pillHTML('▼ SIT', '#402a2a', '#d06d6d', 'A benched player projects better — take him out'));
      else if (verdict === 'close') pills.push(pillHTML('≈ TOSS-UP', '#4a3f30', '#ffc99b', 'Projections within ' + CLOSE_PPG + ' ppg — either is fine'));
      // Matchup: Sleeper's row already prints the game line ("Sun 1:00 PM
      // @ IND"), so instead of a duplicate opp pill we tint that line (green =
      // plus matchup, red = tough) with the Vegas tooltip. Rows where the game
      // line can't be found keep the pill.
      const g = wkOppInfo(p);
      if (g && !tintGameLine(row, nameRow, g)) pills.push(pillHTML(g.txt, g.bg, g.fg, g.tip));
      const v = wkVal(p);
      if (v > 0 || p.pPg != null) {
        pills.push(pillHTML((Math.round(v * 10) / 10) + ' proj', '#26304d', '#00ceb8',
          'Projected points this week (' + state.scoringLabel + ' · sim-engine mean: Clay × Vegas × matchup, league-scored)'));
        const bb = boomBustFor(p, v);
        if (bb) pills.push(bbPillHTML(bb));
      }
      const inner = pills.join('');
      if (row.dataset.mffSig === inner) continue;
      row.dataset.mffSig = inner;
      const ex = row.querySelector('.mff-tr-pills');
      if (ex) ex.remove();
      if (verdict === 'go') {
        row.style.setProperty('background', 'rgba(34, 197, 94, 0.10)', 'important');
        row.style.setProperty('outline', '1px solid #22c55e', 'important');
        row.style.setProperty('outline-offset', '-1px', 'important');
        row.style.removeProperty('box-shadow');
      } else if (verdict === 'sit') {
        row.style.setProperty('background', 'rgba(208, 109, 109, 0.10)', 'important');
        row.style.setProperty('outline', '1px solid #d06d6d', 'important');
        row.style.setProperty('outline-offset', '-1px', 'important');
        row.style.removeProperty('box-shadow');
      } else if (verdict === 'close') {
        row.style.setProperty('background', 'rgba(255, 193, 102, 0.08)', 'important');
        row.style.setProperty('outline', '1px solid #ffc166', 'important');
        row.style.setProperty('outline-offset', '-1px', 'important');
        row.style.removeProperty('box-shadow');
      } else {
        clearRowStyle(row);
      }
      if (inner) {
        const span = document.createElement('span');
        span.className = 'mff-tr-pills';
        span.innerHTML = inner;
        span.style.cssText = 'display:inline-flex;flex-wrap:nowrap;gap:3px;margin-left:6px;' +
          'vertical-align:middle;overflow:hidden;position:relative;z-index:2;';
        // Team-page rows have room — bump the pills from the 8px micro size
        // to a readable 10px. Direct children only: the boom/bust pill nests
        // colored spans that must not pick up their own padding.
        span.querySelectorAll(':scope > span').forEach((s) => {
          s.style.fontSize = '10px';
          s.style.lineHeight = '15px';
          s.style.padding = '0 4px';
        });
        nameRow.appendChild(span);
      }
    }
  }

  // ---------- trade decoration (v0.16.0) ----------
  // Sleeper's Trade Offer modal (.trade-center-wrapper → one
  // .roster-trade-container per manager → RECEIVES/SENDS .panels of
  // .asset-rows). Inject per-asset KTC + Jack's-rank pills, a per-side net
  // line (KTC + optimal-lineup PPG delta), and a verdict wash: winner green,
  // loser red, fair = both orange. 2-way trades only get a verdict; every
  // side always gets its net line.
  function tradeRosterOf(uname) {
    if (!uname) return null;
    const uid = Object.keys(state.userNames).find((id) => state.userNames[id] === uname);
    if (!uid) return null;
    return state.seasonRosters.find((r) => r.owner_id === uid ||
      (Array.isArray(r.co_owners) && r.co_owners.indexOf(uid) !== -1)) || null;
  }
  function tradePickValue(year, roundNum, origRid) {
    // 2027/2028 → team-aware once the season sim has run (generic tier avg
    // before that); 2026 order is known → generic tiers; past 2028 KTC has no
    // anchors → extrapolate off 2028 with a 15%/yr discount (shown with ~).
    const rk = PK_ROUNDS[roundNum - 1];
    if (!rk) return null;
    const baseYear = Math.min(Math.max(year, 2026), 2028);
    const a = pkAnchors(baseYear, rk, pkSf());
    if (!a) return null;
    let v = (baseYear >= 2027 && origRid != null && state.pickSim.status === 'done')
      ? pkTeamPickValue(origRid, baseYear, rk)
      : Math.round((a.e + a.m + a.l) / 3);
    if (year > 2028) v = Math.round(v * Math.pow(0.85, year - 2028));
    return v;
  }
  function tradePickResolve(holderUname, year, rd) {
    // The modal only names the pick's HOLDER ("From antmanna55") — but the
    // traded_picks-adjusted inventory knows which pick(s) that manager
    // actually owns for the year/round. Single match → value by the TRUE
    // origin team's projected finish; multiple matches (own + acquired) →
    // the modal can't say which is offered, so average the candidates;
    // no inventory yet → fall back to assuming it's the holder's own.
    const hr = tradeRosterOf(holderUname);
    const hRid = hr ? hr.roster_id : null;
    const inv = state.pickSim.inv;
    const cands = (hRid != null && inv && inv[hRid])
      ? inv[hRid].filter((p) => p.year === year && p.round === rd) : [];
    const origs = cands.length ? cands.map((c) => c.orig) : (hRid != null ? [hRid] : []);
    if (!origs.length) return { val: tradePickValue(year, rd, null), origs: [], via: null, multi: false };
    const vals = origs.map((o) => tradePickValue(year, rd, o) || 0);
    return {
      val: Math.round(vals.reduce((t, v) => t + v, 0) / vals.length),
      origs, multi: origs.length > 1,
      via: origs.length === 1 && origs[0] !== hRid ? origs[0] : null,
    };
  }
  function tradeAssetInfo(rowEl) {
    const meta = rowEl.querySelector('.meta');
    if (!meta) return null;
    const t1 = meta.querySelector('.meta-text-1');
    const subs = meta.querySelectorAll('.meta-text-2');
    if (!t1 || !subs.length) return null;
    const name = (t1.childNodes[0] ? t1.childNodes[0].textContent : t1.textContent).trim();
    const sub = subs[0].textContent.trim();          // "QB • LAC" | "Draft Pick"
    const fromTo = subs.length > 1 ? subs[subs.length - 1].textContent.trim() : '';
    const pm = name.match(/^(\d{4})\s+(\d+)(?:st|nd|rd|th)?\s*Rd/i);
    if (pm || /draft pick/i.test(sub)) {
      const holder = (fromTo.match(/^(?:From|To)\s+(.+)$/i) || [])[1] || null;
      return { kind: 'pick', el: t1, name, year: pm ? +pm[1] : null, rd: pm ? +pm[2] : null, holder };
    }
    const pos0 = (sub.split('•')[0] || '').trim();
    const pos = pos0 === 'DEF' ? 'DST' : pos0;
    const p = findPlayer(name, pos);
    return { kind: 'player', el: t1, name, pos, p: p || null };
  }
  // ---- KTC value adjustment (verbatim port of keeptradecut.com site.min.js:
  // processV / reverseAdjust / checkEquality / adjustPackage, pulled
  // 2026-07-30). Validated against KTC's own calculator: [5470, 2613] vs
  // [6297] → +1715 to side 2, adjusted totals 8083/8012, Fair Trade. ----
  const KTC_MAXPLAYERVAL = 1e4;
  const KTC_VARIANCE = 5; // KTC's default fairness band (percent of combined total)
  function ktcProcessV(e, a, t, r) {
    var s = (0.05 * Math.pow(e / t, 1.3) + 0.05 * Math.pow(e / (1.05 * a), 6) + 0.1) * e;
    if (r > 0) s *= Math.max(0.6, 1 - 0.15 * r);
    if (s < 0) s /= 4;
    return s;
  }
  function ktcReverseAdjust(e, a, t, r) {
    var s = ktcProcessV(a, a, t, -1), n = a;
    if (s < e) n = Math.max(e / s * a * 0.8, a);
    var l, i, o, p, d = 1, u = 0, c = 1, m = -1;
    for (l = n / 2; d > 0.025 && u <= 10;) {
      i = ktcProcessV(l, n, t, r);
      d = Math.min(Math.abs(i - e) / e, 1);
      if (!(d <= 0.025)) { o = l; p = d * l * 0.75; if (i <= e) l += p; else l -= p; }
      if (d < c) { c = d; m = o; if (m > a) n = m; }
      if (u === 10 && d > 0.05) {
        var f = 0;
        for (l = Math.max(1, m); d > 0.025 && f <= 10;) {
          i = ktcProcessV(l, n, t, r);
          d = Math.min(Math.abs(i - e) / e, 1);
          if (!(d <= 0.025)) { o = l; p = d * l * 0.25; if (i <= e) l += p; else l -= p; }
          if (d < c) { c = d; m = o; if (m > a) n = m; }
          f++;
        }
        l = m;
      }
      u++;
    }
    return Math.round(l);
  }
  function ktcCheckEquality(e, a, t) {
    var r = (e = Math.max(0, e)) + (a = Math.max(0, a)), s = Math.abs(e - a), n = Math.min(100, s / r * 100);
    return !(parseFloat(Math.round(10 * n) / 10) > t);
  }
  // pkg1/pkg2: asset-value arrays. Returns KTC's adjustment: which package is
  // credited (side 1|2), the value, whether KTC would display it, and the
  // adjusted totals used for the fairness verdict.
  function ktcAdjust(pkg1, pkg2, topVal) {
    var adjustment = { side: -1, value: 0, display: false };
    var tOne = pkg1.slice().sort(function (x2, y2) { return y2 - x2; });
    var tTwo = pkg2.slice().sort(function (x2, y2) { return y2 - x2; });
    var one = { totalValue: tOne.reduce(function (x2, y2) { return x2 + y2; }, 0), maxVal: tOne[0] || 0, adjust: 0, rawAdj: 0 };
    var two = { totalValue: tTwo.reduce(function (x2, y2) { return x2 + y2; }, 0), maxVal: tTwo[0] || 0, adjust: 0, rawAdj: 0 };
    var e = 0, a = 0, t = topVal + 80, r = Math.max(one.maxVal, two.maxVal);
    var s = [], n = [], l = -1, i = -1, o = ktcProcessV(0.5 * r, r, t, -1);
    var p, f, c, S, A, V, M, R, w = true, T = 0, P = false, $;
    for (p = 0; p < tOne.length; p++) {
      f = tOne[p];
      if (f < 0.5 * r) l++;
      c = ktcProcessV(f, r, t, l);
      e += c;
      s.push({ adj: c, nerfIndex: l });
    }
    for (p = 0; p < tTwo.length; p++) {
      f = tTwo[p];
      if (f < 0.5 * r) i++;
      c = ktcProcessV(f, r, t, i);
      a += c;
      n.push({ adj: c, nerfIndex: i });
    }
    s.sort(function (x2, y2) { return y2.adj - x2.adj; });
    n.sort(function (x2, y2) { return y2.adj - x2.adj; });
    one.rawAdj = e; two.rawAdj = a;
    var h = one.totalValue ? e / one.totalValue : 0;
    var y = two.totalValue ? a / two.totalValue : 0;
    var v = Math.floor(Math.abs(e - a));
    var k = ktcCheckEquality(one.totalValue, two.totalValue, KTC_VARIANCE);
    var b = ktcCheckEquality(e, a, KTC_VARIANCE);
    var scan = e > a ? n : s;
    for ($ = 0; $ < scan.length; $++) {
      if (v < o && scan[$].adj < v && !P) { T = scan[$].nerfIndex + 1; P = true; }
    }
    if (k && b) {
      if (e > a) {
        adjustment.side = 1;
        S = ktcReverseAdjust(v, r, t, T);
        A = two.totalValue + S - one.totalValue;
        if (A > 0) { adjustment.value = A; one.adjust = A; }
        else { w = false; adjustment.side = 2; adjustment.value = -1 * A; two.adjust = adjustment.value; }
      } else if (a > e) {
        adjustment.side = 2;
        S = ktcReverseAdjust(v, r, t, T);
        A = one.totalValue + S - two.totalValue;
        if (A > 0) { adjustment.value = A; two.adjust = A; }
        else { w = false; adjustment.side = 1; adjustment.value = -1 * A; one.adjust = adjustment.value; }
      }
    } else if (h > y) {
      adjustment.side = 1;
      if (e > a) {
        S = ktcReverseAdjust(v, r, t, T);
        A = two.totalValue + S - one.totalValue;
        if (A > 0) { adjustment.value = A; one.adjust = A; }
        else { w = false; adjustment.side = 2; adjustment.value = Math.abs(A); two.adjust = adjustment.value; }
      } else {
        V = -1;
        if (one.totalValue + one.adjust < two.totalValue + two.adjust) V = 1;
        else if (two.totalValue + two.adjust < one.totalValue + one.adjust) V = 2;
        M = ktcReverseAdjust(Math.abs(one.rawAdj - two.rawAdj), Math.max(one.maxVal, two.maxVal), 10099, T);
        if (M > 0 && V > 0) {
          adjustment.side = V;
          if (V === 2) {
            R = M - (one.totalValue - two.totalValue);
            adjustment.value = R;
            two.adjust = R;
            if (R <= 0) w = false;
          } else {
            R = M - (two.totalValue - one.totalValue);
            if (R > 0) {
              if (R > KTC_MAXPLAYERVAL) { w = false; adjustment.value = 0; adjustment.side = 1; one.adjust = 0; }
              else { adjustment.side = 2; adjustment.value = R; two.adjust = R; }
            } else { adjustment.value = -1 * R; one.adjust = adjustment.value; }
          }
        } else w = false;
      }
    } else {
      adjustment.side = 2;
      if (a > e) {
        S = ktcReverseAdjust(v, r, t, T);
        A = one.totalValue + S - two.totalValue;
        if (A > 0) { adjustment.value = A; two.adjust = A; }
        else { w = false; adjustment.side = 1; adjustment.value = Math.abs(A); one.adjust = adjustment.value; }
      } else {
        V = -1;
        if (one.totalValue + one.adjust < two.totalValue + two.adjust) V = 1;
        else if (two.totalValue + two.adjust < one.totalValue + one.adjust) V = 2;
        M = ktcReverseAdjust(Math.abs(one.rawAdj - two.rawAdj), Math.max(one.maxVal, two.maxVal), 10099, T);
        if (M > 0 && V > 0) {
          adjustment.side = V;
          if (V === 1) {
            R = M - (two.totalValue - one.totalValue);
            adjustment.value = R;
            one.adjust = R;
            if (R <= 0) w = false;
          } else {
            R = M - (one.totalValue - two.totalValue);
            if (R > 0) {
              if (R > KTC_MAXPLAYERVAL) { w = false; adjustment.value = 0; adjustment.side = 1; two.adjust = 0; }
              else { adjustment.side = 1; adjustment.value = R; one.adjust = R; }
            } else { adjustment.value = -1 * R; two.adjust = adjustment.value; }
          }
        } else w = false;
      }
    }
    if (adjustment.value !== 0) {
      if (w) adjustment.display = true;
      if (Math.abs(adjustment.value / (one.totalValue + two.totalValue)) < 0.033) adjustment.display = false;
    } else adjustment.display = false;
    return { side: adjustment.side, value: Math.round(adjustment.value), display: adjustment.display,
      adjTotalOne: Math.round(one.totalValue + one.adjust), adjTotalTwo: Math.round(two.totalValue + two.adjust) };
  }

  // Same-seed before/after season sims → per-side Δ avg wins + Δ title odds.
  // One "after" run covers every side at once; runs async off the decorate
  // tick, result keyed by the trade signature so the bars upgrade in place.
  let _tradeImpactBusy = false;
  async function tradeImpactRun(coreSig, moves) {
    if (_tradeImpactBusy) return;
    _tradeImpactBusy = true;
    try {
      const inp = await pkSimInputs();
      const teams2 = inp.teams.map((t) => {
        const mv = moves[t.rosterId];
        if (!mv) return t;
        const d = {};
        mv.drop.forEach((id) => { d[id] = 1; });
        return Object.assign({}, t, {
          playerIds: t.playerIds.filter((id) => !d[id])
            .concat(mv.add.filter((id) => t.playerIds.indexOf(id) === -1)),
        });
      });
      const tally = (res) => {
        const by = {};
        res.forEach((r) => { by[r.team.rosterId] = { w: r.avgWins, title: r.titleOdds }; });
        return by;
      };
      const before = tally(pkRunSim(inp, inp.teams)); // same seed both runs — deltas isolate the trade
      const after = tally(pkRunSim(inp, teams2));
      const byRid = {};
      Object.keys(after).forEach((rid) => {
        const b = before[rid] || { w: 0, title: 0 };
        byRid[rid] = { dW: after[rid].w - b.w, dT: after[rid].title - b.title };
      });
      state.tradeImpact = { sig: coreSig, byRid };
    } catch (e) {
      state.tradeImpact = { sig: coreSig, byRid: null, err: e.message };
    }
    _tradeImpactBusy = false;
  }
  function decorateTradeModal() {
    const wrap = document.querySelector('.trade-center-wrapper');
    if (!wrap || !state.players.length) return;
    const conts = [...wrap.querySelectorAll('.roster-trade-container')];
    if (!conts.length) return;
    // team-aware pick values need the season sim — kick it lazily
    if (state.seasonLeague && pkDynasty() && simAvailable() && state.pickSim.status === 'idle') setTimeout(ensurePickSim, 0);
    const mk = modeKeys();
    const sides = conts.map((c) => {
      const unameEl = c.querySelector('.username');
      const panels = [...c.querySelectorAll('.panel-container > .panel')];
      const parse = (p) => p ? [...p.querySelectorAll('.asset-row')].map(tradeAssetInfo).filter(Boolean) : [];
      return { c, uname: unameEl ? unameEl.textContent.trim() : '',
        recv: parse(panels[0]), send: parse(panels[1]), panelsEls: panels };
    });
    const coreSig = state.mode + '|' + sides.map((s) =>
      s.uname + ':' + s.recv.concat(s.send).map((a) => a.name).join(',')).join('|');
    const impact = (state.tradeImpact && state.tradeImpact.sig === coreSig) ? state.tradeImpact : null;
    // kick the before/after impact sims once per trade signature
    if (!impact && !_tradeImpactBusy && simAvailable() && state.seasonLeague) {
      const moves = {};
      sides.forEach((s) => {
        const r = tradeRosterOf(s.uname);
        if (!r) return;
        moves[r.roster_id] = {
          add: s.recv.filter((a) => a.kind === 'player' && a.p && a.p.sid).map((a) => String(a.p.sid)),
          drop: s.send.filter((a) => a.kind === 'player' && a.p && a.p.sid).map((a) => String(a.p.sid)),
        };
      });
      if (Object.keys(moves).length) setTimeout(() => tradeImpactRun(coreSig, moves), 0);
    }
    const sig = coreSig + '|' + state.pickSim.status + '|' + (impact ? 'ti' : '');
    if (wrap.dataset.mffSig === sig) return;
    wrap.dataset.mffSig = sig;
    wrap.querySelectorAll('.mff-trade-pill, .mff-trade-net').forEach((el) => el.remove());
    const pVal = (p) => (p && p[mk.ktc]) || 0;
    const topVal = state.players.reduce((t, p) => Math.max(t, p[mk.ktc] || 0), 0);
    const nets = sides.map((s) => {
      // picks resolved against the holder's ACTUAL inventory (true origin)
      const recvVals = s.recv.map((a) => a.kind === 'player' ? pVal(a.p)
        : (tradePickResolve(a.holder || s.uname, a.year, a.rd).val || 0));
      const sendVals = s.send.map((a) => a.kind === 'player' ? pVal(a.p)
        : (tradePickResolve(s.uname, a.year, a.rd).val || 0));
      // KTC's verbatim value adjustment between the two packages: the side
      // consolidating into the best asset gets credited exactly as on
      // keeptradecut.com, and the fairness verdict uses the adjusted totals.
      const adj = (recvVals.length && sendVals.length)
        ? ktcAdjust(recvVals, sendVals, topVal) : null;
      const vRecv = adj ? adj.adjTotalOne : Math.round(recvVals.reduce((t, v) => t + v, 0));
      const vSend = adj ? adj.adjTotalTwo : Math.round(sendVals.reduce((t, v) => t + v, 0));
      // lineup impact: optimal PPG with vs without the trade (players only)
      let ppg = null;
      const r = tradeRosterOf(s.uname);
      if (r && state.seasonLeague) {
        const objs = (r.players || []).map(String).map((sid) => state.byId[sid]).filter(Boolean);
        const recvP = s.recv.filter((a) => a.kind === 'player' && a.p).map((a) => a.p);
        const sendSet = new Set(s.send.filter((a) => a.kind === 'player' && a.p).map((a) => a.p));
        const before = optimalLineup(objs).total;
        const after = optimalLineup(objs.filter((p) => !sendSet.has(p))
          .concat(recvP.filter((p) => objs.indexOf(p) === -1))).total;
        ppg = Math.round((after - before) * 10) / 10;
      }
      return Object.assign(s, { vRecv, vSend, net: vRecv - vSend, ppg, adj });
    });
    // per-asset pills
    sides.forEach((s) => {
      s.recv.concat(s.send).forEach((a) => {
        if (a.el.querySelector('.mff-trade-pill')) return;
        const pill = document.createElement('span');
        pill.className = 'mff-trade-pill';
        pill.style.cssText = 'margin-left:6px;font-size:10px;font-weight:600;color:#00ceb8;white-space:nowrap';
        if (a.kind === 'player') {
          const ktc = a.p ? a.p[mk.ktc] : null;
          const jr = a.p ? a.p[mk.jack] : null;
          pill.textContent = (ktc != null ? ktc.toLocaleString() : '—') + (jr != null ? ' · #' + jr : '');
          pill.title = 'KTC ' + (ktc != null ? ktc.toLocaleString() : '—')
            + (jr != null ? " · Jack's rank #" + jr : '') + ' · ' + state.mode.replace('_', ' ').toUpperCase();
        } else {
          const holder = s.recv.indexOf(a) !== -1 ? (a.holder || s.uname) : s.uname;
          const res = tradePickResolve(holder, a.year, a.rd);
          const nameOfRid = (rid) => {
            const rr = state.seasonRosters.find((x) => x.roster_id === rid);
            return rr ? (state.userNames[rr.owner_id] || 'Team ' + rid) : rid;
          };
          const viaTxt = res.via != null ? ' via ' + nameOfRid(res.via)
            : res.multi ? ' (avg of ' + res.origs.length + ')' : '';
          pill.textContent = (a.year > 2028 ? '~' : '') + (res.val != null ? res.val.toLocaleString() : '—') + viaTxt;
          pill.title = (res.via != null
              ? 'The ' + a.year + ' ' + PK_ROUNDS[a.rd - 1] + ' that ' + holder + ' holds is originally '
                + nameOfRid(res.via) + "'s — valued by THAT team's projected finish"
              : res.multi
                ? holder + ' holds ' + res.origs.length + ' ' + a.year + ' ' + PK_ROUNDS[a.rd - 1] + 's ('
                  + res.origs.map(nameOfRid).join(', ') + ") — the offer doesn't say which, so their values are averaged"
                : holder + "'s own pick — valued by their projected finish")
            + (a.year > 2028 ? '. ~extrapolated: no KTC ' + a.year + ' anchors yet' : '')
            + (state.pickSim.status === 'done' ? '' : '. Generic tier value until the sim runs');
        }
        a.el.appendChild(pill);
      });
    });
    // KTC "Value Adjustment" chips on the credited package (KTC display rules)
    nets.forEach((s) => {
      if (!s.adj || !s.adj.display || !s.adj.value) return;
      if (s.recv.length <= 1 && s.send.length <= 1) return; // KTC only shows it on multi-piece trades
      const panel = s.panelsEls[s.adj.side === 1 ? 0 : 1];
      if (!panel || panel.querySelector('.mff-trade-adj')) return;
      const row = document.createElement('div');
      row.className = 'mff-trade-adj mff-trade-net';
      row.style.cssText = 'margin:3px 0 0;font-size:10px;font-weight:700;color:#00ceb8;opacity:.9';
      row.textContent = 'Value Adjustment +' + s.adj.value.toLocaleString();
      row.title = "KTC's trade-calculator value adjustment (their exact algorithm) — credit to the side consolidating into the best asset.";
      panel.appendChild(row);
    });
    // verdict (2-way only, KTC fairness band on adjusted totals) + net bars
    let verdicts = nets.map(() => null);
    if (nets.length === 2) {
      verdicts = ktcCheckEquality(nets[0].vRecv, nets[0].vSend, KTC_VARIANCE) ? ['fair', 'fair']
        : nets[0].net > 0 ? ['win', 'lose'] : ['lose', 'win'];
    }
    const sgnCol = (v, th) => v > th ? '#22c55e' : v < -th ? '#d06d6d' : '#8b94b3';
    const impactFor = (s) => {
      if (!impact || !impact.byRid) return null;
      const r = tradeRosterOf(s.uname);
      return r ? impact.byRid[r.roster_id] : null;
    };
    nets.forEach((s, i) => {
      const v = verdicts[i];
      const col = v === 'win' ? '#22c55e' : v === 'lose' ? '#d06d6d' : v === 'fair' ? '#ffc166' : '#8b94b3';
      const bar = document.createElement('div');
      bar.className = 'mff-trade-net';
      bar.style.cssText = 'margin:4px 0 2px;padding:4px 8px;border-radius:4px;font-size:11px;font-weight:700;'
        + 'background:rgba(11,18,32,0.55);border-left:3px solid ' + col + ';color:' + col;
      const lbl = v === 'win' ? 'WINS' : v === 'lose' ? 'LOSES' : v === 'fair' ? 'FAIR' : 'NET';
      const seg = (txt, c) => '<span style="color:' + c + '">' + txt + '</span>';
      const imp = impactFor(s);
      let html = 'MFF: ' + esc(s.uname) + ' ' + lbl + ' · ' + (s.net >= 0 ? '+' : '') + s.net.toLocaleString() + ' KTC';
      if (s.ppg != null) html += ' · ' + seg((s.ppg >= 0 ? '+' : '') + s.ppg.toFixed(1) + ' PPG', sgnCol(s.ppg, 0.15));
      if (imp) {
        html += ' · ' + seg((imp.dW >= 0 ? '+' : '') + imp.dW.toFixed(1) + ' W', sgnCol(imp.dW, 0.05))
          + ' · ' + seg((imp.dT >= 0 ? '+' : '') + Math.round(imp.dT * 1000) / 10 + '% title', sgnCol(imp.dT, 0.005));
      } else if (simAvailable() && state.seasonLeague) {
        html += ' · <span style="color:#8b94b3;font-weight:400">simming Δ…</span>';
      }
      bar.innerHTML = html;
      bar.title = 'Net KTC ' + state.mode.replace('_', ' ').toUpperCase() + ' value received minus sent, '
        + "with KTC's own trade-calculator value adjustment applied"
        + (s.adj && s.adj.value ? ' (+' + s.adj.value.toLocaleString() + ' to the '
          + (s.adj.side === 1 ? 'incoming' : 'outgoing') + ' package)' : '') + '. '
        + 'Verdict fair when adjusted totals are within ' + KTC_VARIANCE + '% (KTC default). '
        + 'PPG = optimal-lineup projected points after vs before. '
        + 'W / title = change in simmed season wins and championship odds (same-seed before/after sims).';
      const summ = s.c.querySelector('.roster-trade-summary');
      if (summ) summ.insertBefore(bar, summ.firstChild);
      s.c.style.outline = '1px solid ' + col;
      s.c.style.outlineOffset = '-1px';
      s.c.style.borderRadius = '6px';
    });
  }

  // ---------- draft-board header: what each manager has taken ----------
  // Sleeper's board header names every manager but says nothing about their
  // roster shape, so there's no way to read the room between your picks. Put a
  // QB/RB/WR/TE count under each name, brightened where that manager still
  // hasn't filled his starting slots — the bright letters are "what do the
  // people around me need".
  //
  // Anchored on the display NAME text, not a class: Sleeper's markup churns,
  // but draft_order maps user_id -> slot and userNames maps user_id -> the
  // exact string rendered in the header, so name is the reliable join key.
  const HDR_POS = [['QB', '#c084fc'], ['RB', '#4ade80'], ['WR', '#fb923c'], ['TE', '#60a5fa']];
  // Underdog's board tiles show a coloured QB/RB/WR/TE label row with the
  // counts stacked underneath — Jack asked for ESPN + Sleeper to match that.
  // Label colour is always on (that IS the Underdog look). The COUNT carries
  // the "still needs a starter here" signal: full-strength position colour
  // while short, dim neutral once the slot is filled. Colouring the labels by
  // need instead made the whole box look uncoloured by mid-draft, once every
  // team had met its starter counts.
  function needsBoxHTML(c, req) {
    const cell = (s) => '<div style="flex:1;text-align:center">' + s + '</div>';
    const labels = HDR_POS.map(([pos, col]) => cell(
      '<span style="font-size:8px;font-weight:700;letter-spacing:.2px;color:' + col + '">' + pos + '</span>'
    )).join('');
    const vals = HDR_POS.map(([pos, col]) => {
      const need = c[pos] < (req[pos] || 0);
      return cell('<span style="font-size:10px;font-weight:800;color:' +
        (need ? col : '#767c88') + '">' + c[pos] + '</span>');
    }).join('');
    return '<div style="display:flex;line-height:9px">' + labels + '</div>' +
           '<div style="display:flex;line-height:11px">' + vals + '</div>';
  }
  // Sleeper is the one platform here where DRAFT PICKS GET TRADED, so
  // `draft_slot` is NOT who owns the player — it's the slot the pick
  // originally belonged to. Counting by slot credits a traded pick to the team
  // that sold it (Jack, 2026-08-05). Attribute by who actually took the player
  // instead: `picked_by` (user_id) first, then roster_id via the draft's
  // slot_to_roster_id, and only fall back to the raw slot when the API gives
  // us neither — autopicks sometimes ship an empty picked_by.
  function ownerPosCounts() {
    const fresh = () => ({ QB: 0, RB: 0, WR: 0, TE: 0 });
    const byUser = Object.create(null);
    const byRoster = Object.create(null);
    const bySlot = Object.create(null);
    for (const pk of state.picks || []) {
      const p = matchPick(pk);
      const md = pk.metadata || {};
      const pos = p ? p.s : (md.position === 'DEF' ? 'DST' : md.position);
      if (pos == null) continue;
      const bump = (bag, key) => {
        if (key == null || key === '') return;
        const c = bag[key] || (bag[key] = fresh());
        if (c[pos] != null) c[pos]++;
      };
      bump(byUser, pk.picked_by);
      bump(byRoster, pk.roster_id);
      bump(bySlot, pk.draft_slot);
    }
    // Pick ONE keying for the whole board, don't fall back per manager. A
    // manager who traded ALL his picks away has no byUser entry at all, and a
    // per-manager fallback would drop through to bySlot and hand him back the
    // very picks he sold. Zero picks has to read as zero.
    const any = (bag) => Object.keys(bag).length > 0;
    const bag = any(byUser) ? byUser : any(byRoster) ? byRoster : bySlot;
    const key = any(byUser) ? 'uid' : any(byRoster) ? 'rosterId' : 'slot';
    return { bag: bag, key: key, empty: fresh() };
  }
  function headerStarterReq() {
    const st = (state.draft && state.draft.settings) || {};
    return {
      QB: (st.slots_qb || 0) + (st.slots_super_flex || 0),
      RB: st.slots_rb || 0, WR: st.slots_wr || 0, TE: st.slots_te || 0,
    };
  }
  // Manager names also appear in the pick ticker and roster panels, so a bare
  // name match would decorate those too. The board HEADER is the one element
  // holding MOST of the names — score every common ancestor by how many
  // DISTINCT managers it contains, take the max, then pick the SMALLEST
  // element at that score (body contains them all too, but is enormous).
  // The board header is the one place Sleeper lays every manager out SIDE BY
  // SIDE. The same names also appear stacked in the queue and roster panels,
  // and — the case that broke this — as traded-pick owner labels INSIDE board
  // cells ("-> titsburgh_feelers"), scattered all over the grid.
  //
  // Scoring shared ANCESTORS can't separate those: the nearest common ancestor
  // of the header names is often the same container that holds the cell
  // labels, so the header and the noise are indistinguishable by nesting.
  // Cluster by GEOMETRY instead — sweep the hits by vertical position and take
  // the widest band of distinct names sharing a row (topmost wins ties, since
  // the header sits above the grid). No ancestor walking, no class names.
  function headerBandOf(hits) {
    const withTop = hits
      .map((h) => {
        const r = h.el.getBoundingClientRect();
        return { el: h.el, name: h.name, top: r.top, ok: r.width > 0 && r.height > 0 };
      })
      .filter((h) => h.ok)
      .sort((a, b) => a.top - b.top);
    let best = null;
    for (let i = 0; i < withTop.length; i++) {
      const band = [], names = new Set();
      for (let j = i; j < withTop.length && withTop[j].top - withTop[i].top <= 20; j++) {
        band.push(withTop[j]);
        names.add(withTop[j].name);
      }
      if (!best || names.size > best.names.size) best = { band, names };
    }
    return best && best.names.size >= 3 ? best.band : null;
  }
  // Self-heal against a fixed-height header. If the board header grows, the
  // in-flow row sits under the name and we're done. If it DOESN'T grow (the
  // ESPN helper shipped this same feature as a plain appended block and the
  // counts came out sliced in half by a fixed-height bar), re-anchor the row
  // as an overlay pinned to the cell's bottom — that takes zero layout space,
  // so no ancestor height can clip it. Measured, not guessed, so it adapts to
  // whatever Sleeper's markup is doing without hardcoding their CSS.
  function clippingAncestor(el) {
    for (let a = el; a && a !== document.body; a = a.parentElement) {
      if (getComputedStyle(a).overflowY !== 'visible') return a;
    }
    return null;
  }
  // GROW, don't overlay. An overlay pinned to the cell bottom would sit on top
  // of the manager's name, and the whole point is to read the name AND the
  // positions together. So when the box overflows a fixed-height header we
  // open that header up instead: relax whatever is clipping vertically and
  // give it enough min-height to hold the extra row. Originals are recorded so
  // teardown puts Sleeper's own layout back exactly as it was.
  function fitHeaderRow(row, host) {
    const rr = row.getBoundingClientRect();
    if (!rr.height) return;
    for (let a = host; a && a !== document.body; a = a.parentElement) {
      const cs = getComputedStyle(a);
      const ar = a.getBoundingClientRect();
      const clips = cs.overflowY !== 'visible';
      const short = rr.bottom > ar.bottom + 0.5;
      if (!clips && !short) continue;
      if (!a.dataset.mffHdrGrow) {
        a.dataset.mffHdrGrow = JSON.stringify({
          o: a.style.overflowY || '', h: a.style.height || '', m: a.style.minHeight || '',
        });
      }
      if (clips) a.style.overflowY = 'visible';
      if (short) {
        // Fixed pixel height can't hold the extra line — swap it for a
        // min-height so the element grows instead of slicing the box off.
        if (a.style.height) a.style.height = '';
        a.style.minHeight = Math.ceil(ar.height + (rr.bottom - ar.bottom)) + 'px';
      }
    }
  }
  function decorateDraftHeader() {
    const order = state.draft && state.draft.draft_order;
    if (!order || !state.picks || !state.picks.length) return;
    // display name -> { uid, slot, rosterId }. Identity is the USER, not the
    // slot, so a manager who traded for picks is credited with what he
    // actually drafted rather than what his original slot produced.
    const s2r = (state.draft && state.draft.slot_to_roster_id) || null;
    const whoByName = Object.create(null);
    for (const uid in order) {
      const nm = state.userNames[uid];
      if (!nm) continue;
      const slot = order[uid];
      whoByName[nm.trim()] = { uid: uid, slot: slot, rosterId: s2r ? s2r[slot] : null };
    }
    if (!Object.keys(whoByName).length) return;
    const counts = ownerPosCounts();
    const req = headerStarterReq();
    // TEXT-node walk, not querySelectorAll+textContent: the board is thousands
    // of elements and textContent on each is O(subtree).
    const hits = [];
    const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let n = walk.nextNode(); n; n = walk.nextNode()) {
      const txt = (n.nodeValue || '').trim();
      if (!txt || !(txt in whoByName)) continue;
      const el = n.parentElement;
      if (!el || el.closest('#mff-sidebar')) continue;
      hits.push({ el, name: txt });
    }
    const band = headerBandOf(hits);
    if (!band) return;
    for (const hit of band) {
      const who = whoByName[hit.name];
      if (!who) continue;
      const c = counts.bag[who[counts.key]] || counts.empty;
      // Sit BESIDE the name, not inside it: Sleeper truncates long display
      // names with overflow:hidden + ellipsis, which would clip anything
      // appended within. Same hop-out the season decorator does. Only hop out
      // if the parent belongs to this name alone — otherwise every column's
      // box would pile into one shared container.
      const par = hit.el.parentElement;
      const host = par && !band.some((o) => o.el !== hit.el && par.contains(o.el))
        ? par : hit.el;
      const sig = HDR_POS.map(([pos]) => pos + c[pos] + (c[pos] < (req[pos] || 0) ? '!' : '')).join('');
      let row = host.querySelector(':scope > .mff-hdr-needs');
      if (row && row.dataset.mffSig === sig) continue;
      if (row) row.remove();
      // The header cell is a horizontal flex row, so a plain append lands the
      // counts BESIDE the name and the last one gets squeezed off by the
      // cell's ellipsis. Let the cell wrap and claim a full-width line, which
      // puts the box on its own row underneath the name.
      if (getComputedStyle(host).display.indexOf('flex') >= 0 && !host.dataset.mffHdrWrap) {
        host.dataset.mffHdrWrap = host.style.flexWrap || '-';
        host.style.flexWrap = 'wrap';
      }
      row = document.createElement('div');
      row.className = 'mff-hdr-needs';
      row.dataset.mffSig = sig;
      // pointer-events:none so it never swallows a click on the header cell.
      row.style.cssText = 'flex:0 0 100%;width:100%;margin-top:2px;pointer-events:none';
      row.innerHTML = needsBoxHTML(c, req);
      host.appendChild(row);
      fitHeaderRow(row, host);
    }
  }

  function startDecorating() {
    if (decorateTimer) return;
    decorateTimer = setInterval(() => {
      if (!gateAllowed()) return;
      decoratePlayerList(); decorateRosterPanel(); decorateTeamPage();
      decorateTradeModal(); decorateDraftHeader();
    }, 2000);
    if (gateAllowed()) {
      decoratePlayerList();
      decorateRosterPanel();
      decorateTeamPage();
      decorateTradeModal();
      decorateDraftHeader();
    }
  }
  function stopDecorating() {
    if (decorateTimer) { clearInterval(decorateTimer); decorateTimer = null; }
    document.querySelectorAll('.mff-page-chip, .mff-roster-pills, .mff-corner, .mff-rank-pills, .mff-tr-pills, .mff-trade-pill, .mff-trade-net, .mff-hdr-needs').forEach((c) => c.remove());
    document.querySelectorAll('.mff-opp-hl').forEach(clearOppTint);
    document.querySelectorAll('.player-rank-item2, .draft-roster-list-item, .team-roster-item').forEach((r) => {
      clearRowStyle(r);
      delete r.dataset.mffSig;
    });
    document.querySelectorAll('[data-mff-hdr-grow]').forEach((el) => {
      try {
        const o = JSON.parse(el.dataset.mffHdrGrow);
        el.style.overflowY = o.o; el.style.height = o.h; el.style.minHeight = o.m;
      } catch (e) {}
      delete el.dataset.mffHdrGrow;
    });
    document.querySelectorAll('[data-mff-hdr-wrap]').forEach((el) => {
      el.style.flexWrap = el.dataset.mffHdrWrap === '-' ? '' : el.dataset.mffHdrWrap;
      delete el.dataset.mffHdrWrap;
    });
    document.querySelectorAll('.roster-trade-container').forEach((c) => { c.style.outline = ''; });
    document.querySelectorAll('.trade-center-wrapper').forEach((w) => { delete w.dataset.mffSig; });
  }

  // ---------- init / URL watching ----------
  async function initForDraft(draftId) {
    state.draftId = draftId;
    state.draft = null;
    state.league = null;
    state.picks = [];
    state.myRoster = [];
    state.draftedIds = new Set();
    state.draftedKeys = new Set();
    state.manualDrafted = new Set();
    state.manualMine = new Set();
    state.searchQ = '';
    state.tracking = false;
    state.mySlot = null;
    state.myUserId = null;
    stopPolling();
    buildPanel();
    startDecorating();
    render();
    fetchInjuries(); // draft rec rows show injury chips too (12h-cached dump)
    try {
      const saved = await store.get(['sleeperDraft_' + draftId, 'sleeperHelper.username']);
      const prefs = saved['sleeperDraft_' + draftId];
      if (saved['sleeperHelper.username']) state.username = saved['sleeperHelper.username'];
      state.draft = await api('/draft/' + draftId);
      // League doc: scoring adjustment + dynasty detection + ticker names
      if (state.draft && state.draft.league_id) {
        try { state.league = await api('/league/' + state.draft.league_id); } catch (e) { state.league = null; }
        try {
          const users = await api('/league/' + state.draft.league_id + '/users');
          if (Array.isArray(users)) {
            for (const u of users) state.userNames[u.user_id] = u.display_name || u.username;
          }
        } catch (e) { /* best-effort */ }
      }
      applyLeagueScoring(state.league && state.league.scoring_settings);
      state.modeDetected = await detectMode();
      if (prefs) {
        state.mySlot = prefs.slot || null;
        state.myUserId = prefs.userId || null;
        state.mode = prefs.mode || state.mode;
        state.modeManual = !!prefs.modeManual;
        let src = prefs.rankSource || state.rankSource;
        src = SOURCE_MIGRATE[src] || src;
        state.rankSource = SOURCES[src] ? src : MODES[state.mode].src;
        state.posFilter = prefs.posFilter || 'ALL';
        state.sortVor = !!prefs.sortVor;
        state.notify = prefs.notify !== false;
        state.manualDrafted = new Set(prefs.manualDrafted || []);
        state.manualMine = new Set(prefs.manualMine || []);
        if (prefs.tracking && state.mySlot) {
          state.tracking = true;
          startPolling();
          // re-save so the background watcher gets the meta snapshot even
          // for drafts tracked before v0.10 (and wake it)
          saveDraftPrefs();
          try { chrome.runtime.sendMessage({ type: 'mffWatch', draftId }, () => chrome.runtime.lastError); } catch (e) {}
        }
      } else if (state.modeDetected) {
        applyMode(state.modeDetected, false);
      }
      state.statusMsg = state.players.length + ' players · data ' + state.exportedAt;
    } catch (e) {
      state.statusMsg = 'Draft load failed: ' + e.message;
    }
    render();
  }

  // SPA URL watcher: draft rooms flip to DRAFT mode, league pages flip to
  // SEASON mode; the header toggle can override until the URL next changes.
  let lastHref = null;
  function onUrlChange() {
    const did = detectDraftId();
    const lid = detectLeagueId();
    if (did) {
      if (did !== state.draftId) {
        state.appMode = 'draft';
        initForDraft(did);
      } else if (state.appMode !== 'draft') {
        state.appMode = 'draft';
        render();
      }
    } else if (lid) {
      if (state.draftId) { state.draftId = null; stopPolling(); }
      if (lid !== state.seasonLeagueId) {
        state.appMode = 'season';
        initForLeague(lid);
      } else if (state.appMode !== 'season') {
        state.appMode = 'season';
        render();
      }
    } else if (state.draftId || state.seasonLeagueId) {
      state.draftId = null;
      state.seasonLeagueId = null;
      destroyPanel();
    }
  }
  function watchUrl() {
    setInterval(() => {
      if (location.href === lastHref) return;
      lastHref = location.href;
      onUrlChange();
    }, URL_WATCH_MS);
  }

  async function main() {
    await loadPlayers();
    store.get(['mff_jacks_boards']).then((r) => applyBridgeJackBoards(r && r.mff_jacks_boards));
    refreshJackBoards(); // non-blocking; baked boards work until it lands
    if (MOCK && MOCK.vegas) { // harness stand-in for the live site-lines fetch
      window.BETTING_2026 = MOCK.vegas; // season-sim engine reads gameTotals here
      buildSchedule(MOCK.vegas.gameTotals);
      state.wkPropsAll = MOCK.vegas.weeklyProps || null;
    }
    try {
      const saved = await store.get(['sleeperHelper.username']);
      if (saved['sleeperHelper.username']) state.username = saved['sleeperHelper.username'];
    } catch (e) {}
    lastHref = location.href;
    onUrlChange();
    watchUrl();
  }

  window.__mffSleeper = { state, render, pollOnce, initForDraft, initForLeague, wkVal, kickerProjFor, dstProjFor,
    ensurePickSim, pkTeamPickValue, pkExpFinish, simAvailable, engineMeanFor, engineWeekMap };
  gateInit(() => { try { render(); } catch (_) {} });
  main();
})();
