/* MFF Underdog Draft Helper — sidebar (v0.5)
 * - Click a rec → expand inline profile (does NOT mark drafted; use search to log picks)
 * - Shows R#, UD ADP, Proj PPG, Portfolio % per card
 * - Highlights stack opportunities (QB ↔ same-team WR/TE on roster)
 * - Look-ahead simulator: when not your turn, recs project forward to your next pick
 */
(function () {
  "use strict";
  if (window.__mffSidebarLoaded) return;
  window.__mffSidebarLoaded = true;

  // --- Live Vegas overlay (v0.10.52) ---------------------------------------
  // The bundled data/playoff_sos_2026.js is a static snapshot; its
  // gameTotal/teamSpread/impliedTotal go stale as books move lines. On load,
  // fetch the site's live betting JSON (via background — CORS-free) and
  // overwrite those three fields in place. rank/label/color stay bundled
  // (they blend Clay unit grades etc. that only live in the site's app.js).
  // Fails silently: no network -> bundled numbers stand.
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
    chrome.runtime.sendMessage({ type: 'mff-vegas-fetch' }, (res) => {
      if (chrome.runtime.lastError || !res || !res.ok || !res.data) return;
      const n = _mffApplyLiveVegas(res.data.gameTotals);
      if (n) console.log('[MFF] live Vegas overlay: ' + n + ' SOS records refreshed'
        + (res.data.generatedAt ? ' (site lines from ' + res.data.generatedAt + ')' : ''));
    });
  } catch (_) {}

  // --- Sim Lab season PPG overlay (v0.18.3) --------------------------------
  // sim_proj_2026.json seasonPpg rows are [half, ppr, std] keyed by Clay
  // names — Underdog is half-PPR, so index 0 replaces the baked pPg
  // verbatim. Applied once both the fetch and players.json have landed;
  // K/DST keep the baked numbers (their site models are separate).
  let _mffSimSeason = null;
  function _mffSimNorm(n) {
    let s = String(n || '').toLowerCase().trim()
      .replace(/\s+(jr\.?|sr\.?|iii|ii|iv|v)$/, '')
      .replace(/['’`.,]/g, '').replace(/-/g, ' ').replace(/\s+/g, ' ').trim();
    return s;
  }
  const _MFF_SIM_ALIASES = [
    ['kenneth walker', 'ken walker'], ['cameron ward', 'cam ward'],
    ['kenneth gainwell', 'kenny gainwell'], ['chigoziem okonkwo', 'chig okonkwo'],
    ['marquise brown', 'hollywood brown'], ['joshua palmer', 'josh palmer'],
  ];
  function _mffApplySimSeason() {
    if (!_mffSimSeason || !state.players || !state.players.length) return;
    let n = 0;
    for (const p of state.players) {
      if (p.s === 'K' || p.s === 'DST') continue;
      const sp = _mffSimSeason[_mffSimNorm(p.n)];
      if (sp && typeof sp[0] === 'number') { p.pPg = sp[0]; n++; }
    }
    if (n) console.log('[MFF] Sim Lab season PPG applied to ' + n + ' players');
  }
  try {
    chrome.runtime.sendMessage({ type: 'mff-simproj-fetch' }, (res) => {
      if (chrome.runtime.lastError || !res || !res.ok || !res.data || !res.data.seasonPpg) return;
      const ix = Object.create(null);
      const sp = res.data.seasonPpg;
      for (const k of Object.keys(sp)) ix[_mffSimNorm(k)] = sp[k];
      for (const [a, b] of _MFF_SIM_ALIASES) {
        if (ix[a] === undefined && ix[b] !== undefined) ix[a] = ix[b];
        if (ix[b] === undefined && ix[a] !== undefined) ix[b] = ix[a];
      }
      _mffSimSeason = ix;
      _mffApplySimSeason();
    });
  } catch (_) {}

  // TEAM_SIZE/TOTAL_PICKS are mutable now — auto-detect updates them when the
  // ribbon shows we're in a non-12-team draft (Underdog runs 6/8/10/12).
  let TEAM_SIZE = 12;
  let TOTAL_PICKS = TEAM_SIZE * 18;
  // v0.9.68: forward-declared so wireUp() can assign and outer scope
  // (manual slot change handler, enterDraftMode) can call it without
  // strict-mode "ReferenceError: _doBootstrapRef is not defined".
  let _doBootstrapRef = null;

  // Parse the current Underdog draft id from the URL — used as the chrome.storage
  // key so reloading or re-navigating to the same draft restores state cleanly,
  // while a *different* draft starts fresh. Underdog URL: /draft/<uuid>
  function currentDraftId() {
    try {
      const m = (location.pathname || '').match(/\/draft\/([0-9a-f-]{8,})/i);
      return m ? m[1] : null;
    } catch (_) { return null; }
  }
  const STORAGE_KEY_PREFIX = 'mff_draft_';

  const SIDEBAR_HTML = `
<div id="mff-sidebar">
  <div id="mff-header">
    <div class="title">MFF DRAFT HELPER</div>
    <div class="controls">
      <button id="mff-collapse" title="Collapse">_</button>
      <button id="mff-close" title="Hide">×</button>
    </div>
  </div>
  <div id="mff-resize-n" class="mff-resize-edge" title="Drag to resize height (top)"></div>
  <div id="mff-resize-e" class="mff-resize-edge" title="Drag to resize width"></div>
  <div id="mff-resize-s" class="mff-resize-edge" title="Drag to resize height"></div>
  <div id="mff-resize" title="Drag to resize"></div>
  <div id="mff-body">
    <!-- v0.9.14: Premium gate. Shown when no premium MFF user is detected;
         everything else is hidden behind it. Auto-unlocks the moment the
         site bridge reports a premium-flagged user. -->
    <div id="mff-lock" class="mff-section" style="display:none">
      <div class="lock-icon">🔒</div>
      <h3 class="lock-title">MFF Draft Helper — Premium</h3>
      <div class="lock-msg" id="mff-lock-msg">Sign in at myfantasyfootball.co to unlock the draft helper.</div>
      <a class="start-btn" id="mff-lock-btn" href="https://myfantasyfootball.co" target="_blank" rel="noopener noreferrer">Open MyFantasyFootball</a>
      <div class="lock-status" id="mff-lock-status"></div>
    </div>
    <!-- v0.9.22: Setup screen removed from default flow. The slot auto-
         detects from Underdog's draft ribbon; if it's wrong the user can
         override from the Settings tab. The hidden grid is kept here so
         the existing slot-grid binding code still works without changes. -->
    <div id="mff-setup" class="mff-section" style="display:none">
      <div class="slot-row" id="mff-slot-grid"></div>
      <button class="start-btn" id="mff-start" style="display:none">Start Tracking</button>
    </div>
    <!-- v0.9.12: Tabbed sidebar. Draft tab is the mid-draft live view;
         Settings tab holds format / rank-source / slot config that you set
         once and rarely touch again. -->
    <div id="mff-tabs" style="display:none">
      <button class="mff-tab active" data-tab="rankings">Rankings</button>
      <button class="mff-tab" data-tab="roster">Roster</button>
      <button class="mff-tab" data-tab="projections">Proj</button>
      <button class="mff-tab" data-tab="settings">Settings</button>
    </div>

    <div id="mff-pick-line" style="display:none"></div>

    <div class="mff-section" id="mff-roster-wrap" style="display:none">
      <h3>Optimal Roster</h3>
      <div id="mff-roster">
        <div class="pos pos-qb"><div class="v" id="r-QB">2</div><div class="l">QB</div></div>
        <div class="pos pos-rb"><div class="v" id="r-RB">6</div><div class="l">RB</div></div>
        <div class="pos pos-wr"><div class="v" id="r-WR">7</div><div class="l">WR</div></div>
        <div class="pos pos-te"><div class="v" id="r-TE">2</div><div class="l">TE</div></div>
      </div>
      <div id="mff-target-row">
        <div class="pos pos-qb"><div class="v" id="t-QB">2</div><div class="l">QB</div></div>
        <div class="pos pos-rb"><div class="v" id="t-RB">6</div><div class="l">RB</div></div>
        <div class="pos pos-wr"><div class="v" id="t-WR">7</div><div class="l">WR</div></div>
        <div class="pos pos-te"><div class="v" id="t-TE">2</div><div class="l">TE</div></div>
      </div>
      <!-- v0.9.67: VOR-banked row + scarcity hints. Per position:
             - banked VOR (sum of VOR drafted at that pos)
             - "next +X" = best VOR available, with optional ↓Y scarcity
               indicator showing dropoff to your next pick
           Uses vor or vorSf based on active format. -->
      <div id="mff-vor-row" style="display:flex;gap:6px;margin-top:6px;font-size:.62rem;justify-content:center;color:#94a3b8;flex-wrap:wrap">
        <span id="v-QB">QB —</span>
        <span id="v-RB">RB —</span>
        <span id="v-WR">WR —</span>
        <span id="v-TE">TE —</span>
      </div>
      <!-- v0.9.68: position-level recommendation. Combines VOR scarcity
           (now vs next pick), slot need, and roster balance into a single
           "Suggested: X" line above the player recs. -->
      <div id="mff-pos-suggest" style="margin-top:6px;font-size:.7rem;color:#94a3b8;text-align:center"></div>
      <!-- v0.10.56: VALUE BOARD — per-position chart of value still on the
           shelf (avg VOR of top-3 available) vs how filled-up the roster is
           at that position. The ×mult badge is the heavy buff/nerf the REC
           sort applies; tuning differs for Best Ball vs Redraft. -->
      <div id="mff-value-chart" style="margin-top:6px"></div>
      <div id="mff-flags"></div>
      <!-- Next-pick advance rate by position — uses
           BBM_PICK_BY_RANK_ROUND lookups for the user's current
           round + their next positional rank in each. Populated by
           renderNextPickRates() on every render. -->
      <div id="mff-next-pick-rates" style="margin-top:8px"></div>
      <!-- Construction checklist — pass/fail items derived from BBM IV/V/VI
           historical advance-rate analysis. Populated by renderConstructionChecklist
           on every render; shows current roster against year-stable structural rules. -->
      <div id="mff-construction-check" style="margin-top:8px"></div>
    </div>
    <div class="mff-section" id="mff-recs-wrap" style="display:none">
      <div id="mff-pos-toggle" style="display:flex;gap:4px;margin-bottom:6px;align-items:center">
        <button class="pos-filter active" data-pos="ALL">ALL</button>
        <button class="pos-filter" data-pos="QB">QB</button>
        <button class="pos-filter" data-pos="RB">RB</button>
        <button class="pos-filter" data-pos="WR">WR</button>
        <button class="pos-filter" data-pos="TE">TE</button>
        <button class="sort-toggle" id="mff-sort-toggle" data-sort="rank" title="Sort by Rank (default) or VOR" style="margin-left:auto;font-size:9px;padding:3px 7px;background:#2a2c33;border:1px solid #3a3d45;border-radius:3px;color:#cbd5e1;cursor:pointer;font-weight:600;letter-spacing:.5px">RANK</button>
      </div>
      <!-- TOP 3 PICKS — always REC-scored (roster need + stacks + tier cliffs
           + ADP wait fade + value pockets) regardless of the list sort mode. -->
      <div id="mff-top3"></div>
      <div id="mff-recs"></div>
    </div>

    <!-- Projections tab — live PPG-by-position with portfolio/total/room baselines -->
    <div class="mff-section" id="mff-projections-wrap" style="display:none">
      <div id="mff-proj-baseline" class="mff-proj-baseline"></div>
      <div id="mff-proj-info" class="mff-proj-info"></div>
      <div id="mff-proj-grid" class="mff-proj-grid"></div>
      <div id="mff-proj-total" class="mff-proj-total" style="display:none"></div>
      <div id="mff-proj-roster" class="mff-proj-roster"></div>
    </div>

    <!-- Settings tab content — hidden by default, shown when Settings tab clicked -->
    <div class="mff-section" id="mff-settings-wrap" style="display:none">
      <h3>Account</h3>
      <div id="mff-account-row">
        <span class="acct-status" id="mff-acct-status">·</span>
        <span class="acct-email" id="mff-acct-email">—</span>
        <span class="acct-tier" id="mff-acct-tier"></span>
      </div>

      <h3 style="margin-top:8px">Format</h3>
      <!-- v0.18.0: "Best Ball" removed as a format. Jack's best-ball board was
           consolidated into the redraft board, so the only rank boards left are
           Redraft (p.rank) and Superflex (p.jSf). Underdog is a best-ball site,
           so the ALGORITHM here always runs best-ball tuning (mode "bb": BBM
           advance rates, stacks, structural checks) regardless of this pick —
           see state.isRedraft, which is pinned false in this extension. -->
      <select id="mff-format-select" class="mff-select" title="Rank board. Underdog always scores with best-ball tuning.">
        <option value="rd">Redraft</option>
        <option value="sf">Superflex</option>
      </select>
      <span id="mff-fmt-auto" title="Format auto-detected from page" style="font-size:9px;color:#22c55e;font-style:italic;display:none;margin-top:2px">auto-detected</span>

      <h3 style="margin-top:6px">Rank Source</h3>
      <select id="mff-rank-select" class="mff-select" title="Rank source">
        <option value="jacks">Jack's</option>
        <option value="ud">UD ADP</option>
        <option value="fp">FP</option>
        <option value="consensus">Consensus</option>
      </select>

      <h3 style="margin-top:6px">ADP Movement Window</h3>
      <select id="mff-adp-window-select" class="mff-select" title="Show ADP delta vs this many days ago">
        <option value="7">7 days</option>
        <option value="14">14 days</option>
        <option value="30">30 days</option>
      </select>

      <h3 style="margin-top:6px">Draft Slot</h3>
      <div class="slot-row" id="mff-slot-grid-settings"></div>

      <h3 style="margin-top:8px">Portfolio</h3>
      <button id="mff-sync-btn" class="start-btn" style="margin-bottom:4px">Sync from Underdog</button>
      <div id="mff-sync-status" style="font-size:10px;color:#8a8d96;line-height:1.4"></div>
    </div>
  </div>
</div>`;

  const state = {
    players: [], byName: new Map(), drafted: new Set(),
    tiers: null, // Jack's tier boundaries per rank field: {rank (redraft), jSf: [{a,l,n}]}
    myRoster: [], pickNum: 1, slot: null, history: [],
    mode: "manual", portfolio: null,
    rankSrc: "jacks", // 'jacks' | 'ud' | 'fp' | 'consensus'
    posFilter: "ALL", // 'ALL' | 'QB' | 'RB' | 'WR' | 'TE'
    sortBy: "rank",   // 'rank' | 'rec' | 'vor' — toggleable in the rec list header
    // v0.18.0: PINNED FALSE on Underdog. Every UD contest is best ball, so the
    // algorithm always runs mode "bb" (BBM advance rates, stack bonuses,
    // structural checklist, best-ball value curves). The FORMAT dropdown now
    // only picks which of Jack's rank BOARDS to read (redraft vs superflex) —
    // his best-ball board was consolidated into the redraft board.
    isRedraft: false,
    expandedRec: null,
    // Format toggle. When superflex is on, ranks come from p.sfRank (derived
    // from p.sfa, the Underdog Superflex ADP). Auto-detected from the page;
    // user can override with the SF toggle button.
    isSuperflex: false,
    superflexSource: null, // 'auto' | 'manual'
    // v0.9.69: ADP movement tracking. adpHistory holds up to 30 daily
    // snapshots ({ date, capturedAt, adps: { name: { bbm, sf } } }).
    // adpWindow is the user's selected lookback (7 | 14 | 30).
    adpHistory: [],
    adpWindow: 7,
    // Projections tab baseline: 'portfolio' | 'total' | 'room'.
    projBaseline: 'portfolio',
  };
  window.__mffSidebar = state;

  // Full NFL team name → abbreviation, for compact display in rec cards.
  const TEAM_ABBR = {
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL",
    "Buffalo Bills": "BUF", "Carolina Panthers": "CAR", "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE", "Dallas Cowboys": "DAL",
    "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX",
    "Kansas City Chiefs": "KC", "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC",
    "Los Angeles Rams": "LAR", "Miami Dolphins": "MIA", "Minnesota Vikings": "MIN",
    "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG",
    "New York Jets": "NYJ", "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT",
    "San Francisco 49ers": "SF", "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN", "Washington Commanders": "WAS"
  };
  function teamAbbr(t) {
    if (!t) return "";
    if (TEAM_ABBR[t]) return TEAM_ABBR[t];
    // Already an abbrev (3-4 chars all caps) → pass through
    if (/^[A-Z]{2,4}$/.test(t)) return t;
    // Fallback: return as-is so the user still sees something
    return t;
  }

  // Dome / fixed-roof / retractable stadiums. ATL DET HOU IND LV MIN NO ARI
  // are the standard 8 (true domes + retractables that close in Dec/Jan);
  // DAL LAR LAC added because AT&T and SoFi both have roofs that shield
  // passing conditions even when not strictly "closed".
  const DOME_TEAMS = new Set(['ATL','DET','HOU','IND','LV','MIN','NO','ARI','DAL','LAR','LAC']);
  // Returns the host team's abbr for a playoff_sos matchup record:
  //   m.home === true  → player's team is host
  //   m.home === false → opponent is host
  function _hostAbbr(playerTeamAbbr, m) {
    return m && m.home ? playerTeamAbbr : (m ? m.opp : null);
  }
  // Renders a small circled-D suffix when the host stadium is a dome. Inline,
  // low visual weight, inherits the pill's color so the badge isn't louder
  // than the SOS signal itself.
  function _domeSuffix(playerTeamAbbr, m) {
    const host = _hostAbbr(playerTeamAbbr, m);
    if (!host || !DOME_TEAMS.has(host)) return '';
    return '<span style="font-size:9px;opacity:.7;margin-left:2px" title="Dome — ' + host + '">Ⓓ</span>';
  }

  // ---------- Jack's board tiers ----------
  // state.tiers[field] = sorted [{a, l, n}] boundaries baked by the exporter
  // ("rank" = his live redraft board, "jSf" = superflex). A tier applies from
  // rank `a` until the next boundary — same as the site's _tierLabelForRank.
  // Color cycle is the site's .myrank-num tier-X palette (styles/main.css).
  // NOTE: r.flags.tier (VOR cliff) is a different, unrelated concept.
  const JACK_TIER_LABELS = ['S','A','B','C','D','E','F','G','H','I','J','K','L','M','N','O','P','Q','R','T','U','V','W','X','Y','Z'];
  const JACK_TIER_COLORS = ['#eab308','#ef4444','#3b82f6','#22c55e','#a855f7','#f97316','#9ca3af','#ec4899','#06b6d4','#84cc16','#f43f5e','#6366f1','#fbbf24','#14b8a6','#d946ef','#ea580c','#38bdf8','#a3e635','#fb7185'];
  function jackTierColor(label) {
    const i = JACK_TIER_LABELS.indexOf(label);
    return JACK_TIER_COLORS[(i >= 0 ? i : 0) % JACK_TIER_COLORS.length];
  }
  function jackTierList() {
    if (!state.tiers) return null;
    return (state.isSuperflex ? state.tiers.jSf : state.tiers.rank) || null;
  }
  // Rank on the board the active tier list describes. In SF mode p.sfRank can
  // be an ADP fallback when Jack hasn't ranked the player — only a real jSf
  // counts there; otherwise p.rank, the consolidated redraft/best-ball board.
  function jackTierRank(p) {
    return state.isSuperflex ? (p.jSf != null ? p.jSf : null) : p.rank;
  }
  function jackTierFor(rank) {
    const list = jackTierList();
    if (!list || !list.length || rank == null) return null;
    let cur = null;
    for (const t of list) { if (t.a <= rank) cur = t; else break; }
    return cur;
  }

  async function loadPlayers() {
    const url = chrome.runtime.getURL("data/players.json");
    const res = await fetch(url);
    if (!res.ok) throw new Error("HTTP " + res.status);
    const j = await res.json();
    state.players = j.players;
    state.tiers = j.tiers || null; // Jack's tier boundaries per rank field
    state.byName = new Map(state.players.map(p => [p.n, p]));
    // v0.9.72: overlay the latest live ADP snapshot so the extension uses
    // today's ADP instead of whatever was baked into players.json. The
    // daily refresh writes mff_player_adps_snapshot via _dailyAdpRefresh,
    // and storage onChanged will re-overlay if a fresher snapshot lands
    // mid-session. Read here is best-effort — if no snapshot, fall back to
    // the static udA/sfa from data/players.json silently.
    try {
      await new Promise((r) => {
        try {
          chrome.storage.local.get(['mff_player_adps_snapshot'], (res2) => {
            const snap = res2 && res2.mff_player_adps_snapshot;
            if (snap && snap.adps) {
              _applyLiveAdpToPlayers(snap.adps);
              console.log('[MFF/adp] applied live ADP from snapshot date',
                          snap.date, '— covers', Object.keys(snap.adps).length, 'players');
            }
            r();
          });
        } catch (_) { r(); }
      });
    } catch (_) {}
    _mffApplySimSeason(); // sim fetch may have landed before players.json
  }

  // v0.9.72: apply a live-ADP map to state.players. Map shape:
  //   { [playerName]: { bbm: number|null, sf: number|null } }
  // Only overrides when a value is present — preserves static fallbacks.
  function _applyLiveAdpToPlayers(adpMap) {
    if (!adpMap || !state.byName) return 0;
    let applied = 0;
    for (const name in adpMap) {
      const p = state.byName.get(name);
      if (!p) continue;
      const ent = adpMap[name];
      if (ent && ent.bbm != null && !isNaN(ent.bbm)) { p.udA = ent.bbm; applied++; }
      if (ent && ent.sf != null && !isNaN(ent.sf)) { p.sfa = ent.sf; }
    }
    return applied;
  }

  // v0.9.73: portfolio is keyed by Underdog's player name (e.g. "Brian
  // Robinson") because picks come straight from UD. The bundled players.json
  // stores the canonical name (e.g. "Brian Robinson Jr.") in `n`. Use udN
  // — UD's preferred form — as a fallback so exposure %, co-occurrence,
  // and decorator badges all light up for players whose names differ in
  // suffix/punctuation. Returns the key that exists in the lookup map, or
  // null if neither does.
  function _portfolioKey(p, mapObj) {
    if (!p || !mapObj) return null;
    if (p.n != null && Object.prototype.hasOwnProperty.call(mapObj, p.n)) return p.n;
    if (p.udN != null && Object.prototype.hasOwnProperty.call(mapObj, p.udN)) return p.udN;
    return null;
  }

  function injectSidebar() {
    const wrap = document.createElement("div");
    wrap.innerHTML = SIDEBAR_HTML;
    document.body.appendChild(wrap.firstElementChild);
    wireUp();
  }

  // ---------- State persistence (chrome.storage.local) ----------
  // Saves on every meaningful change so a refresh / accidental navigation
  // restores the live draft cleanly. Keyed by Underdog's draft UUID — different
  // drafts get different storage slots; only the current draft is restored.
  let _persistTimer = null;
  function persistState() {
    const id = currentDraftId();
    if (!id) return;
    // Debounce — many calls in quick succession (multiple picks coming through
    // bootstrap) collapse to one write.
    if (_persistTimer) clearTimeout(_persistTimer);
    _persistTimer = setTimeout(() => {
      try {
        const payload = {
          version: 1,
          savedAt: Date.now(),
          slot: state.slot,
          teamSize: TEAM_SIZE,
          pickNum: state.pickNum,
          mode: state.mode,
          drafted: Array.from(state.drafted),
          // Persist only the player names — they'll be rehydrated to objects
          // via state.byName on restore.
          myRoster: state.myRoster.map(p => p.n),
          history: state.history.map(h => ({ name: h.name, mine: h.mine, prevPick: h.prevPick })),
          // UI prefs — survive a refresh too.
          rankSrc: state.rankSrc,
          posFilter: state.posFilter,
          sortBy: state.sortBy,
          isSuperflex: state.isSuperflex,
          isRedraft: state.isRedraft,
          superflexSource: state.superflexSource,
        };
        chrome.storage.local.set({ [STORAGE_KEY_PREFIX + id]: payload });
      } catch (e) { /* ignore */ }
    }, 250);
  }

  function restoreState(cb) {
    const id = currentDraftId();
    if (!id) { cb && cb(false); return; }
    try {
      chrome.storage.local.get([STORAGE_KEY_PREFIX + id], (res) => {
        const saved = res && res[STORAGE_KEY_PREFIX + id];
        if (!saved || !saved.drafted) { cb && cb(false); return; }
        // Need state.byName populated first — caller wires this after
        // loadPlayers() resolves.
        state.slot = saved.slot || null;
        state.pickNum = saved.pickNum || 1;
        state.mode = saved.mode || 'manual';
        state.drafted = new Set(saved.drafted || []);
        state.myRoster = (saved.myRoster || [])
          .map(n => state.byName.get(n))
          .filter(Boolean);
        state.history = saved.history || [];
        if (saved.rankSrc) state.rankSrc = saved.rankSrc;
        if (saved.posFilter) state.posFilter = saved.posFilter;
        if (saved.sortBy) state.sortBy = saved.sortBy;
        if (typeof saved.isSuperflex === "boolean") state.isSuperflex = saved.isSuperflex;
        // v0.18.0: isRedraft is pinned false on Underdog (always best-ball
        // tuning). Older saves may carry isRedraft:true — deliberately ignored.
        state.isRedraft = false;
        if (saved.superflexSource) state.superflexSource = saved.superflexSource;
        if (saved.teamSize && saved.teamSize !== TEAM_SIZE) {
          setTeamSize(saved.teamSize);
        }
        // Reflect restored prefs in the toggle UI
        const rs = document.getElementById("mff-rank-select");
        if (rs) rs.value = state.rankSrc;
        applyFormatUI();
        document.querySelectorAll("#mff-pos-toggle .pos-filter").forEach(x => {
          x.classList.toggle("active", x.dataset.pos === state.posFilter);
        });
        console.log('[MFF] restored draft', id, '→', state.drafted.size, 'picks,', state.myRoster.length, 'mine');
        cb && cb(true);
      });
    } catch (_) { cb && cb(false); }
  }

  // ---------- Format detection (Best Ball vs Superflex) ----------
  // Underdog labels superflex contests with the word "Superflex" somewhere on
  // the draft page (often in the contest header or scoring panel). We do a
  // simple text scan; cheap because we early-exit at the first match. Keep
  // this conservative — false-positive on Best Ball is way worse than missing
  // a Superflex auto-flag (the user can always click the toggle).
  function detectSuperflexFromPage() {
    try {
      // GATE 1: only autodetect on an actual draft page. The lobby /
      // contest-list views surface "Superflex" text from OTHER tournaments
      // the user owns (left rail, draft selector, navigation), which
      // triggered false positives before any draft was opened.
      const path = (location && location.pathname) || "";
      const onDraftPage = /\/draft(?:\/|$)/i.test(path) || /\/draft-/i.test(path);
      if (!onDraftPage) return false;
      // GATE 2: title must mention Superflex. The draft page sets the tab
      // title to the contest name — Underdog includes "Superflex" only when
      // the active contest is actually SF.
      if (/superflex/i.test(document.title || "")) return true;
      // GATE 3: scoped element search — only inspect the draft-board
      // container, not the whole document. Containers Underdog typically
      // uses: anything with a class containing "draft" + "board"/"header".
      // Fall back to the whole document only if no scoped match found
      // AND we already passed the URL gate.
      const scopes = document.querySelectorAll(
        '[class*="draft-board" i], [class*="DraftBoard" i], ' +
        '[class*="draft-header" i], [class*="DraftHeader" i], ' +
        '[class*="contest-header" i], [class*="ContestHeader" i]'
      );
      const roots = scopes.length ? Array.from(scopes) : [document.body];
      for (const root of roots) {
        const candidates = root.querySelectorAll('h1, h2, h3, h4, [class*="title" i], [class*="format" i], [class*="scoring" i]');
        for (const el of candidates) {
          const text = (el.innerText || "").trim();
          if (!text || text.length > 200) continue;
          if (/superflex/i.test(text)) return true;
        }
      }
    } catch (_) { /* ignore */ }
    return false;
  }

  function applyFormatUI() {
    const sel = document.getElementById("mff-format-select");
    if (sel) sel.value = state.isSuperflex ? "sf" : "rd";
    const auto = document.getElementById("mff-fmt-auto");
    if (auto) auto.style.display = (state.superflexSource === "auto") ? "" : "none";
  }

  // ---------- Auto-detect team size (rebuild slot grid if it changed) ----------
  // Walk the ribbon and find the largest pick-in-round (the "X" in "1.X | Y").
  // In a snake draft, max(pickInRound) = team size.
  function inferTeamSizeFromRibbon() {
    let max = 0;
    const candidates = document.querySelectorAll('*');
    for (const el of candidates) {
      const text = (el.innerText || '').trim();
      if (!text || text.length > 200) continue;
      const m = text.match(/(\d+)\.(\d+)\s*\|\s*\d+/);
      if (!m) continue;
      const pir = parseInt(m[2], 10);
      if (pir > max) max = pir;
    }
    return max > 0 ? max : null;
  }

  function setTeamSize(n) {
    if (!n || n < 4 || n > 16 || n === TEAM_SIZE) return;
    TEAM_SIZE = n;
    TOTAL_PICKS = TEAM_SIZE * 18;
    // v0.9.12: rebuild BOTH slot grids (setup + Settings tab) using the
    // shared builder so they stay in sync.
    if (typeof buildSlotGrid === 'function') {
      buildSlotGrid('mff-slot-grid');
      buildSlotGrid('mff-slot-grid-settings');
    }
    const lbl = document.querySelector('#mff-setup label');
    if (lbl) lbl.textContent = 'Your slot (1–' + TEAM_SIZE + '):';
    console.log('[MFF] team size →', TEAM_SIZE);
  }

  // ---------- Turn alert ----------
  // Beeps once and flashes the sidebar header when it just became your turn.
  // Only fires on the *transition* from "not-my-turn" to "my-turn" so it
  // doesn't repeat on every render.
  let _wasMyTurn = false;
  let _audioCtx = null;
  function turnAlertOnce() {
    // Sound: short two-tone beep using Web Audio (no asset needed)
    try {
      _audioCtx = _audioCtx || new (window.AudioContext || window.webkitAudioContext)();
      const ctx = _audioCtx;
      const beep = (freq, when, dur) => {
        const o = ctx.createOscillator();
        const g = ctx.createGain();
        o.frequency.value = freq;
        o.type = 'sine';
        g.gain.setValueAtTime(0, ctx.currentTime + when);
        g.gain.linearRampToValueAtTime(0.18, ctx.currentTime + when + 0.01);
        g.gain.linearRampToValueAtTime(0, ctx.currentTime + when + dur);
        o.connect(g); g.connect(ctx.destination);
        o.start(ctx.currentTime + when);
        o.stop(ctx.currentTime + when + dur + 0.05);
      };
      beep(880, 0, 0.18);
      beep(1175, 0.20, 0.22);
    } catch (_) { /* ignore — autoplay/audio policy */ }
    // Flash the sidebar header
    const header = document.getElementById('mff-header');
    if (header) {
      header.style.transition = 'background 0.18s';
      const orig = header.style.background;
      let n = 0;
      const flash = () => {
        header.style.background = (n % 2 === 0) ? '#22c55e' : (orig || '');
        n++;
        if (n < 6) setTimeout(flash, 220);
        else header.style.background = orig || '';
      };
      flash();
    }
    // Desktop notification (best-effort — silent if not granted)
    try {
      if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
        new Notification('MFF Draft Helper', { body: "You're on the clock!", silent: false });
      } else if (typeof Notification !== 'undefined' && Notification.permission === 'default') {
        Notification.requestPermission();
      }
    } catch (_) { /* ignore */ }
  }
  function maybeFireTurnAlert() {
    const myTurn = isMyTurn(state.pickNum, state.slot);
    if (myTurn && !_wasMyTurn) turnAlertOnce();
    _wasMyTurn = myTurn;
  }

  // v0.9.99: a player whose `t` is a mock-draft team projection (devy /
  // 2026 prospect) shouldn't trigger same-team correlations against real
  // NFL teammates. Heuristic: no NFL PPG in any of the last three seasons.
  // Real veterans, even ones playing limited roles, will have a non-null
  // value somewhere in p23/p24/p25.
  function _isProjectedTeam(p) {
    if (!p || !p.t) return true; // FA / no team → don't match
    // v0.10.37: Don't treat drafted rookies as "projected." The old check
    // flagged any player missing p25/p24/p23 (NFL season-PPG history) as a
    // projection, which catches rookies like Ted Hurst whose NFL team IS
    // confirmed (post-draft) — they just don't have NFL history yet. If
    // Underdog lists them with an ADP (udA) or rank (fpR/slR/rank), the
    // team assignment is real and stack/team correlation should fire.
    if (p.udA != null || p.fpR != null || p.slR != null || p.rank != null) return false;
    return p.p25 == null && p.p24 == null && p.p23 == null;
  }

  // ---------- Stack detection ----------
  function detectStack(player, myRoster) {
    if (!player.t) return null;
    if (_isProjectedTeam(player)) return null;
    const sameTeam = myRoster.filter(r => r.t === player.t && !_isProjectedTeam(r));
    if (!sameTeam.length) return null;
    if (player.s === "QB") {
      const targets = sameTeam.filter(r => r.s === "WR" || r.s === "TE");
      if (targets.length) return { kind: "qb-stack", with: targets };
    } else if (player.s === "WR" || player.s === "TE") {
      const qb = sameTeam.find(r => r.s === "QB");
      if (qb) return { kind: "with-qb", with: [qb] };
    }
    return null;
  }

  // v0.9.74: detect "TEAM" — a softer correlation than QB stack. Same NFL
  // team as someone already on your roster, but only for skill-skill pairs
  // that share game-script tailwinds (RB↔WR, RB↔TE, WR↔WR, WR↔TE).
  // Excluded:
  //   - RB↔RB: same backfield is anti-correlated (touches cannibalize)
  //   - TE↔TE: rare to play 2 TEs, target competition
  //   - QB↔* and *↔QB: already handled by detectStack (don't double-trigger)
  // Returns { kind:'team', with:[roster_mates] } or null. Caller should only
  // surface this when detectStack returns null (STACK takes precedence).
  function detectTeam(player, myRoster) {
    if (!player.t) return null;
    if (_isProjectedTeam(player)) return null;
    if (player.s !== "RB" && player.s !== "WR" && player.s !== "TE") return null;
    const sameTeam = myRoster.filter(r => r.t === player.t && !_isProjectedTeam(r));
    if (!sameTeam.length) return null;
    const allowedPairs = {
      RB: { WR: 1, TE: 1 },
      WR: { RB: 1, WR: 1, TE: 1 },
      TE: { RB: 1, WR: 1 },
    };
    const ok = allowedPairs[player.s] || {};
    const mates = sameTeam.filter(r => ok[r.s]);
    if (!mates.length) return null;
    return { kind: "team", with: mates };
  }

  // Reverse direction: are any rec players on the same team as my non-QB, allowing future stack
  // (used for adding "BUILDS STACK" badge for QBs who pair with my existing WRs/TEs, even before
  //  picking the QB — already covered by detectStack above).

  // v0.9.12: shared slot-set logic. The setup screen and the Settings tab
  // each render their own slot-grid; clicking either calls this so state +
  // visual highlights stay in sync across both grids.
  // v0.9.22: also re-bootstraps from the page when slot changes — so when
  // the slot is set/changed mid-session, picks get re-attributed correctly
  // to the user's roster.
  function setSlot(i) {
    const prev = state.slot;
    state.slot = i;
    document.querySelectorAll("#mff-slot-grid button, #mff-slot-grid-settings button").forEach(x => {
      x.classList.toggle("active", parseInt(x.dataset.slot, 10) === i);
    });
    const badge = document.getElementById("mff-detected-slot");
    if (badge) badge.style.display = "none";
    persistState();
    // Re-bootstrap so picks are re-attributed against the (now corrected) slot.
    if (prev !== i && typeof _doBootstrapRef === 'function') {
      _doBootstrapRef({ silent: true });
    }
    if (typeof render === "function") render();
  }

  function buildSlotGrid(gridId) {
    const grid = document.getElementById(gridId);
    if (!grid) return;
    grid.innerHTML = '';
    for (let i = 1; i <= TEAM_SIZE; i++) {
      const b = document.createElement("button");
      b.textContent = i;
      b.dataset.slot = i;
      if (state.slot === i) b.classList.add("active");
      b.addEventListener("click", () => setSlot(i));
      grid.appendChild(b);
    }
  }

  function wireUp() {
    buildSlotGrid("mff-slot-grid");
    buildSlotGrid("mff-slot-grid-settings");

    // Sync portfolio from Underdog (manual click in Settings tab).
    const syncBtn = document.getElementById("mff-sync-btn");
    if (syncBtn) {
      syncBtn.addEventListener("click", () => {
        if (typeof syncPortfolioFromUnderdog === "function") syncPortfolioFromUnderdog();
      });
    }

    // v0.9.68: 3-tab structure — Rankings / Roster / Settings.
    //   Rankings → player rec list (mff-recs-wrap), top pick line
    //   Roster   → optimal-roster widget + VOR analysis + suggested pos
    //   Settings → format/rank source/slot config
    function _show(id, on) {
      const el = document.getElementById(id);
      if (el) el.style.display = on ? "" : "none";
    }
    document.querySelectorAll("#mff-tabs .mff-tab").forEach(btn => {
      btn.addEventListener("click", () => {
        const tab = btn.dataset.tab;
        document.querySelectorAll("#mff-tabs .mff-tab").forEach(x => x.classList.remove("active"));
        btn.classList.add("active");
        // Pick-line shown on all live-draft views (rankings/roster/projections).
        _show("mff-pick-line", tab === "rankings" || tab === "roster" || tab === "projections");
        _show("mff-recs-wrap", tab === "rankings");
        _show("mff-roster-wrap", tab === "roster");
        _show("mff-projections-wrap", tab === "projections");
        _show("mff-settings-wrap", tab === "settings");
        if (tab === "projections") renderProjections();
      });
    });

    // ---------- Auto-detect the user's draft slot ----------
    // Try once now, then poll until the live-watcher has loaded the player
    // pool and the Underdog ribbon is present. Pre-selects the matching slot
    // button. User can still click any other slot to override.
    let _detectAttempts = 0;
    const _MAX_DETECT_ATTEMPTS = 30; // 30 × 1s = 30s window
    // Shared "apply a detection result" path — pre-clicks the slot button
    // (same flow as a manual click) + shows the auto-detected badge.
    function applyDetectedSlot(res) {
      if (state.slot) return false; // user/earlier detection already set it
      if (!res || !res.slot || res.slot < 1 || res.slot > TEAM_SIZE) return false;
      const btn = document.querySelector('#mff-slot-grid button[data-slot="' + res.slot + '"]');
      if (!btn) return false;
      document.querySelectorAll("#mff-slot-grid button").forEach(x => x.classList.remove("active"));
      btn.classList.add("active");
      state.slot = res.slot;
      // Show a small "Auto-detected" badge so the user knows what happened.
      // (Pre-refactor code referenced an out-of-scope `grid` here, so the
      // badge threw a ReferenceError and never actually rendered.)
      let badge = document.getElementById("mff-detected-slot");
      if (!badge) {
        const gridEl = document.getElementById("mff-slot-grid");
        if (gridEl && gridEl.parentNode) {
          badge = document.createElement("div");
          badge.id = "mff-detected-slot";
          badge.style.cssText = "font-size:10px;color:#22c55e;margin-top:4px;font-style:italic";
          gridEl.parentNode.insertBefore(badge, gridEl.nextSibling);
        }
      }
      if (!badge) { console.log("[MFF] auto-detected user slot:", res); return true; }
      const via = res.source ? " [" + res.source + "]" : "";
      badge.textContent = "Auto-detected: slot " + res.slot +
        (res.username ? " (" + res.username + ")" : "") + via + " — click another slot to override";
      badge.style.display = "";
      console.log("[MFF] auto-detected user slot:", res);
      return true;
    }
    // v0.16.0: username/account-based detection like the Sleeper/ESPN
    // helpers. injected.js snoops the draft room's own authenticated XHRs:
    // /v1/user (logged-in id + username) and /v2/drafts/<uuid> (entries with
    // pick_order). Matching MY user id to MY entry is exact — no DOM
    // heuristics — and also yields the true team count. Shapes are walked
    // defensively (UD has changed schema before); any miss returns null and
    // the pickposition DOM fallback below still runs.
    let _userDetectInFlight = false;
    async function detectSlotByUsername() {
      const m = (location.pathname || '').match(/\/draft\/([0-9a-f][0-9a-f-]{10,})/i);
      const draftId = m ? m[1] : null;
      const cached = await udBulk(draftId ? ['/v1/user', '/v2/drafts/' + draftId]
                                          : ['/v1/user', '/v2/drafts/'], 3000);
      let me = cached['/v1/user'];
      if (me && me.user) me = me.user;
      const myId = me && me.id;
      const myName = (me && (me.username || me.display_name)) || null;
      if (myId == null) return null;
      // Draft detail: the URL's draft if cached, else the only cached one.
      const want = draftId ? '/v2/drafts/' + draftId : null;
      const dKeys = Object.keys(cached).filter((k) => /^\/v2\/drafts\/[^/]+$/.test(k));
      const key = (want && cached[want]) ? want : (dKeys.length === 1 ? dKeys[0] : null);
      let draft = key ? cached[key] : null;
      if (draft && draft.draft) draft = draft.draft;
      if (!draft) return null;
      const entries = draft.draft_entries || draft.entries || [];
      const mine = entries.find((e) => e && (e.user_id === myId || (e.user && e.user.id === myId)));
      if (!mine) return null;
      const ord = (e) => (e && e.pick_order != null) ? e.pick_order
                       : (e && e.position != null) ? e.position : null;
      let slot = ord(mine);
      if (slot == null) return null;
      // Normalize to 1-based: entries' pick_orders are a permutation, so a
      // 0 anywhere in the set means the scheme is 0-based.
      const orders = entries.map(ord).filter((v) => v != null);
      if (orders.length && Math.min.apply(null, orders) === 0) slot += 1;
      // Entry count is the authoritative team size (ribbon heuristic can lag).
      if (entries.length >= 2 && entries.length !== TEAM_SIZE) setTeamSize(entries.length);
      return { slot: slot, source: 'username', username: myName };
    }
    function tryAutoDetectSlot() {
      // Stop if user already picked a slot manually
      if (state.slot) return;
      // Account-based path first (exact when the snoop cache has the data).
      if (!_userDetectInFlight) {
        _userDetectInFlight = true;
        detectSlotByUsername()
          .then((res) => { _userDetectInFlight = false; if (res) applyDetectedSlot(res); })
          .catch(() => { _userDetectInFlight = false; });
      }
      if (typeof window.__mffDetectMySlot !== "function") {
        if (_detectAttempts++ < _MAX_DETECT_ATTEMPTS) setTimeout(tryAutoDetectSlot, 1000);
        return;
      }
      // Team size first — slot detection's snake-derivation depends on it.
      // live-watcher exposes inferTeamSize() implicitly via its public surface,
      // but to be safe we read the ribbon ourselves with the same heuristic.
      const detectedSize = inferTeamSizeFromRibbon();
      if (detectedSize && detectedSize !== TEAM_SIZE) setTeamSize(detectedSize);
      const res = window.__mffDetectMySlot();
      // v0.9.1: only trust username-based detection. The highlight-only
      // source (no username cross-check) is the path that wrongly latched
      // onto slot 1 pre-draft. If username detection isn't ready yet, keep
      // polling — don't lock in a guess that might be wrong.
      const trusted = res && (res.source === 'username' || res.source === 'username+derived'
                              || res.source === 'highlight' || res.source === 'highlight+derived'
                              || res.source === 'pickposition');
      if (trusted && applyDetectedSlot(res)) return;
      // Not yet — keep trying until ribbon loads
      if (_detectAttempts++ < _MAX_DETECT_ATTEMPTS) setTimeout(tryAutoDetectSlot, 1000);
    }
    // Kick off shortly after wireUp so the ribbon has a chance to render.
    setTimeout(tryAutoDetectSlot, 800);
    document.getElementById("mff-start").addEventListener("click", () => {
      if (!state.slot) { alert("Pick your draft slot first."); return; }
      document.getElementById("mff-setup").style.display = "none";
      // v0.9.12: show tab toggle + pick line + draft view (roster + recs).
      // Settings view stays hidden until the user clicks the Settings tab.
      ["mff-tabs", "mff-pick-line", "mff-roster-wrap", "mff-recs-wrap"].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.display = "";
      });
      render();
      // Auto-sync from the Underdog page on start. Silent (no confirm/alert)
      // since this is the natural ingest point — existing picks on the ribbon
      // get pulled in once, and live-watcher's pulse handles every subsequent
      // pick automatically. Manual SYNC FROM PAGE is still available as a
      // fallback (e.g. mid-draft re-sync).
      doBootstrapFromPage({ silent: true });
      // Kick off the player-list decorator so STACK / NEED flags appear
      // even when no portfolio has been synced from the MFF site yet.
      if (typeof startExposureDecorator === "function") startExposureDecorator();
    });
    document.getElementById("mff-collapse").addEventListener("click", () => {
      const sb = document.getElementById("mff-sidebar");
      const collapsing = !sb.classList.contains("collapsed");
      if (collapsing) {
        // Stash the resized height so we can restore it on expand. The
        // .collapsed CSS rule sets height:38px, but an inline height set by
        // the resize handles wins over it — clear the inline height so the
        // CSS rule actually applies.
        sb._mffPrevHeight = sb.style.height || "";
        sb.style.height = "";
      } else if (sb._mffPrevHeight !== undefined) {
        sb.style.height = sb._mffPrevHeight;
        delete sb._mffPrevHeight;
      }
      sb.classList.toggle("collapsed");
    });
    document.getElementById("mff-close").addEventListener("click", () => {
      document.getElementById("mff-sidebar").style.display = "none";
    });

    // Shared sync routine — used by the auto-sync triggered when the user clicks
    // START. opts.silent skips confirm/alert popups (auto-sync should never
    // block the UI). opts.retry controls how long we'll wait for
    // __mffBootstrap to be installed by live-watcher.js (it loads async after
    // the page boots). Returns the number of picks ingested (0 if none found
    // yet — that's a normal state for "draft hasn't started").
    // Expose doBootstrapFromPage to outer scope (enterDraftMode needs it).
    function doBootstrapFromPage(opts) {
      opts = opts || {};
      const silent = !!opts.silent;
      const retry = opts.retry != null ? opts.retry : (silent ? 8 : 0);
      function applyDrafted(drafted) {
        state.drafted.clear(); state.myRoster = []; state.history = []; state.pickNum = 1;
        let missCount = 0;
        for (const { name, pickNum, team, pos } of drafted) {
          const player = findPlayerLoose(name, team, pos);
          if (!player) {
            missCount++;
            console.warn("[MFF] bootstrap pick not in pool:", name,
                         "pickNum=" + pickNum, "team=" + (team || "—"), "pos=" + (pos || "—"));
            continue;
          }
          state.pickNum = pickNum;
          const mine = isMyTurn(pickNum, state.slot);
          state.drafted.add(player.n);
          if (mine) state.myRoster.push(player);
          state.history.push({ name: player.n, mine, prevPick: pickNum });
          state.pickNum = pickNum + 1;
        }
        state.mode = "live";
        const okCount = drafted.length - missCount;
        console.log("[MFF] auto-synced", okCount, "/", drafted.length, "picks (" + missCount + " missed); pickNum =", state.pickNum, "myRoster =", state.myRoster.length);
        render();
      }
      function tryOnce(remaining) {
        if (!window.__mffBootstrap) {
          if (remaining > 0) {
            // Watcher hasn't loaded yet — retry shortly. Silent path doesn't
            // alert; the user will see the live indicator update once it lands.
            setTimeout(() => tryOnce(remaining - 1), 500);
            return 0;
          }
          if (!silent) alert("Bootstrap not loaded yet.");
          return 0;
        }
        // v0.9.22: slot is no longer required before bootstrapping. Picks
        // still get added to state.drafted (so Best Available filters them
        // correctly); myRoster stays empty until the slot is known. When
        // the slot is set later via setSlot(), bootstrap re-runs and the
        // roster gets re-attributed.
        if (!state.slot && !silent) {
          // Only alert in non-silent mode (manual sync); silent path keeps going.
        }
        const drafted = window.__mffBootstrap();
        if (!drafted || !drafted.length) {
          if (!silent) {
            alert("No drafted players detected on page. Make sure the pick history ribbon is visible.");
          }
          // No picks yet is a normal state for an autosync at draft-start —
          // live-watcher will dispatch each pick as it's made.
          return 0;
        }
        if (!silent && !confirm("Found " + drafted.length + " drafted players. Replace current state?")) return 0;
        applyDrafted(drafted);
        return drafted.length;
      }
      return tryOnce(retry);
    }
    // Expose to enterDraftMode (defined at outer scope).
    _doBootstrapRef = doBootstrapFromPage;

    // Rank source dropdown
    const rankSelect = document.getElementById("mff-rank-select");
    if (rankSelect) {
      rankSelect.value = state.rankSrc;
      rankSelect.addEventListener("change", () => {
        state.rankSrc = rankSelect.value;
        render();
      });
    }

    // v0.9.69: ADP movement window dropdown.
    const adpWinSelect = document.getElementById("mff-adp-window-select");
    if (adpWinSelect) {
      adpWinSelect.value = String(state.adpWindow || 7);
      adpWinSelect.addEventListener("change", () => {
        const v = parseInt(adpWinSelect.value, 10) || 7;
        state.adpWindow = v;
        try { chrome.storage.local.set({ mff_adp_window: v }); } catch (_) {}
        render();
        // Re-decorate UD's DOM badges so the indicator reflects new window.
        if (typeof clearExposureBadges === 'function') clearExposureBadges();
        if (typeof decoratePlayerList === 'function') setTimeout(decoratePlayerList, 50);
      });
    }

    // Format dropdown — Redraft board vs Superflex board. Manual change
    // overrides auto-detect. isRedraft stays false either way: Underdog is a
    // best-ball site, so the scoring/tuning is always mode "bb".
    const fmtSelect = document.getElementById("mff-format-select");
    if (fmtSelect) {
      fmtSelect.value = state.isSuperflex ? "sf" : "rd";
      fmtSelect.addEventListener("change", () => {
        state.isSuperflex = fmtSelect.value === "sf";
        state.isRedraft = false;
        state.superflexSource = "manual";
        applyFormatUI();
        persistState();
        render();
      });
    }

    // Kick off superflex auto-detect once the page settles. Underdog labels
    // superflex contests with the word "Superflex" somewhere in the draft view
    // (header / scoring section / contest title). Re-poll for ~30s in case the
    // label loads asynchronously.
    let _sfDetectAttempts = 0;
    function tryAutoDetectSuperflex() {
      // Don't override the user's manual choice.
      if (state.superflexSource === "manual") return;
      const detected = detectSuperflexFromPage();
      if (detected !== state.isSuperflex) {
        state.isSuperflex = detected;
        state.superflexSource = "auto";
        applyFormatUI();
        persistState();
        render();
      }
      if (_sfDetectAttempts++ < 30) setTimeout(tryAutoDetectSuperflex, 1000);
    }
    setTimeout(tryAutoDetectSuperflex, 500);

    // Position filter toggle (ALL/QB/RB/WR/TE) — narrows the rec list to one
    // position. Selection persists with the rest of draft state.
    // v0.9.90: VOR sort toggle in the pos-filter row
    const sortBtn = document.getElementById("mff-sort-toggle");
    if (sortBtn) {
      function refreshSortBtn() {
        sortBtn.dataset.sort = state.sortBy;
        sortBtn.textContent = state.sortBy === "vor" ? "VOR" : state.sortBy === "rec" ? "REC" : "RANK";
        sortBtn.style.background = state.sortBy === "vor" ? "#3a4a3a" : state.sortBy === "rec" ? "#4a3a14" : "#2a2c33";
        sortBtn.style.color = state.sortBy === "vor" ? "#86efac" : state.sortBy === "rec" ? "#fbbf24" : "#cbd5e1";
        sortBtn.title = state.sortBy === "rec"
          ? "REC: roster-aware picks — rank boosted for stacks + positions of need, faded where you're already loaded"
          : state.sortBy === "vor"
            ? "Sorted by Value Over Replacement"
            : "Sorted by rank (click: REC → VOR → RANK)";
      }
      refreshSortBtn();
      sortBtn.addEventListener("click", () => {
        state.sortBy = state.sortBy === "rank" ? "rec" : state.sortBy === "rec" ? "vor" : "rank";
        refreshSortBtn();
        if (typeof persist === "function") persist();
        if (typeof render === "function") render();
      });
    }

    document.querySelectorAll("#mff-pos-toggle .pos-filter").forEach(b => {
      b.addEventListener("click", () => {
        state.posFilter = b.dataset.pos || "ALL";
        document.querySelectorAll("#mff-pos-toggle .pos-filter").forEach(x => x.classList.remove("active"));
        b.classList.add("active");
        render();
      });
    });

    const sidebarEl = document.getElementById("mff-sidebar");
    makeDraggable(sidebarEl, document.getElementById("mff-header"));
    makeResizable(sidebarEl, document.getElementById("mff-resize"), "corner");
    makeResizable(sidebarEl, document.getElementById("mff-resize-e"), "east");
    makeResizable(sidebarEl, document.getElementById("mff-resize-s"), "south");
    makeResizable(sidebarEl, document.getElementById("mff-resize-n"), "north");
    restoreSidebarSize(sidebarEl);
    window.addEventListener("message", onPageMessage);
  }

  // Parse Underdog "My Drafts" CSV into portfolio structure.
  // Most Underdog exports have one row per slot per draft, with columns:
  //   Draft Entry ID, Tournament, Slot/Position, Player Name, ...
  // We group rows by Draft Entry ID, build per-team player lists, then
  // compute counts and pair-counts.
  function parsePortfolioCsv(text) {
    const rows = parseCsv(text);
    if (!rows.length) return null;
    const header = rows[0].map(h => h.replace(/^"|"$/g, "").trim().toLowerCase());
    const findCol = (names) => {
      for (const n of names) {
        const i = header.indexOf(n);
        if (i >= 0) return i;
      }
      // partial match
      for (let i = 0; i < header.length; i++) {
        for (const n of names) if (header[i].includes(n)) return i;
      }
      return -1;
    };
    const draftCol = findCol(["draft entry id", "draft entry", "entry id", "draft id"]);
    const playerCol = findCol(["player name", "player", "name", "appearance"]);
    if (draftCol < 0 || playerCol < 0) {
      throw new Error("CSV missing 'Draft Entry ID' or 'Player Name' columns");
    }
    const teamsByDraft = new Map();
    for (let i = 1; i < rows.length; i++) {
      const r = rows[i];
      if (!r[draftCol] || !r[playerCol]) continue;
      const draftId = r[draftCol].replace(/"/g, "").trim();
      const player = r[playerCol].replace(/"/g, "").trim();
      if (!teamsByDraft.has(draftId)) teamsByDraft.set(draftId, new Set());
      teamsByDraft.get(draftId).add(player);
    }
    const teams = [...teamsByDraft.values()].map(s => [...s]);
    const numTeams = teams.length;
    if (numTeams === 0) return null;
    const counts = {};
    const pairs = {};
    for (const team of teams) {
      const sorted = [...team].sort();
      for (let i = 0; i < sorted.length; i++) {
        counts[sorted[i]] = (counts[sorted[i]] || 0) + 1;
        for (let j = i + 1; j < sorted.length; j++) {
          const k = sorted[i] + "|" + sorted[j];
          pairs[k] = (pairs[k] || 0) + 1;
        }
      }
    }
    const percent = {};
    for (const name in counts) {
      percent[name] = (counts[name] / numTeams) * 100;
    }
    return { teams, counts, pairs, percent, numTeams };
  }

  function parseCsv(text) {
    const rows = [];
    let row = [];
    let cur = "";
    let inQuotes = false;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (inQuotes) {
        if (c === '"') {
          if (text[i + 1] === '"') { cur += '"'; i++; }
          else { inQuotes = false; }
        } else { cur += c; }
      } else {
        if (c === '"') inQuotes = true;
        else if (c === ',') { row.push(cur); cur = ""; }
        else if (c === '\n') { row.push(cur); rows.push(row); row = []; cur = ""; }
        else if (c === '\r') { /* skip */ }
        else cur += c;
      }
    }
    if (cur || row.length) { row.push(cur); rows.push(row); }
    return rows.filter(r => r.length > 1);
  }

  function makeDraggable(el, handle) {
    let dx = 0, dy = 0, sx = 0, sy = 0;
    handle.addEventListener("mousedown", (e) => {
      if (e.target.tagName === "BUTTON") return;
      sx = e.clientX; sy = e.clientY;
      const r = el.getBoundingClientRect();
      dx = sx - r.left; dy = sy - r.top;
      const headerH = handle.offsetHeight || 38;
      e.preventDefault();
      const mv = (ev) => {
        el.style.right = "auto";
        let newLeft = ev.clientX - dx;
        let newTop = ev.clientY - dy;
        // Clamp so the header (the only drag handle) is always grabbable.
        // Vertical: top must keep the header within the viewport — otherwise
        // the user has no way to drag the panel back down.
        const maxTop = Math.max(0, window.innerHeight - headerH);
        newTop = Math.max(0, Math.min(maxTop, newTop));
        // Horizontal: keep at least 80px of the panel on screen so the
        // close/collapse buttons + part of the title remain reachable.
        const w = el.offsetWidth || 360;
        const minLeft = Math.min(0, 80 - w);
        const maxLeft = Math.max(0, window.innerWidth - 80);
        newLeft = Math.max(minLeft, Math.min(maxLeft, newLeft));
        el.style.left = newLeft + "px";
        el.style.top = newTop + "px";
      };
      const up = () => {
        document.removeEventListener("mousemove", mv);
        document.removeEventListener("mouseup", up);
      };
      document.addEventListener("mousemove", mv);
      document.addEventListener("mouseup", up);
    });
  }

  // Resize modes:
  //   "corner" — drag bottom-right corner, both width AND height change
  //   "east"   — drag right edge, width only
  //   "south"  — drag bottom edge, height only
  //   "north"  — drag top edge, height only; bottom stays pinned so the
  //              panel shrinks upward from the bottom-fixed anchor. Lets
  //              users grab the panel when it overflows the viewport and
  //              the south/corner handles are scrolled off-screen.
  function makeResizable(el, handle, mode) {
    if (!handle) return;
    mode = mode || "corner";
    handle.addEventListener("mousedown", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const r = el.getBoundingClientRect();
      const startX = e.clientX, startY = e.clientY;
      const startW = r.width, startH = r.height;
      const startTop = r.top;
      const fixedBottom = r.top + r.height; // for "north" mode
      // Lock the pinned corner so the box grows toward bottom-right.
      el.style.right = "auto";
      el.style.left = r.left + "px";
      el.style.top = r.top + "px";
      // Cancel any inherited max-height so user can grow vertically.
      el.style.maxHeight = "none";
      const mv = (ev) => {
        if (mode === "corner" || mode === "east") {
          const w = Math.max(280, Math.min(900, startW + (ev.clientX - startX)));
          el.style.width = w + "px";
        }
        if (mode === "corner" || mode === "south") {
          const h = Math.max(160, Math.min(window.innerHeight - 20, startH + (ev.clientY - startY)));
          el.style.height = h + "px";
        }
        if (mode === "north") {
          // Drag DOWN = shrink (top moves down, bottom stays put).
          // Drag UP   = grow (top moves up, bottom stays put).
          const desiredH = startH - (ev.clientY - startY);
          const h = Math.max(160, Math.min(window.innerHeight - 20, desiredH));
          el.style.height = h + "px";
          el.style.top = (fixedBottom - h) + "px";
        }
      };
      const up = () => {
        document.removeEventListener("mousemove", mv);
        document.removeEventListener("mouseup", up);
        try {
          chrome.storage.local.set({
            mff_sidebar_size: { w: el.offsetWidth, h: el.offsetHeight }
          });
        } catch (_) {}
      };
      document.addEventListener("mousemove", mv);
      document.addEventListener("mouseup", up);
    });
  }

  function restoreSidebarSize(el) {
    try {
      chrome.storage.local.get(["mff_sidebar_size"], (res) => {
        const sz = res && res.mff_sidebar_size;
        if (!sz) return;
        if (sz.w) el.style.width = sz.w + "px";
        if (sz.h) { el.style.maxHeight = "none"; el.style.height = sz.h + "px"; }
      });
    } catch (_) {}
  }

  function onPageMessage(ev) {
    if (!ev.data || ev.data.source !== "mff-underdog") return;
    const msg = ev.data;
    if (msg.type === "pick") {
      const found = findPlayerLoose(msg.player, msg.team, msg.pos);
      if (!found) {
        console.warn("[MFF] Live pick not in pool:", msg.player,
                     "pickNum=" + (msg.pickNum || "?"),
                     "team=" + (msg.team || "—"),
                     "pos=" + (msg.pos || "—"));
        return;
      }
      if (state.drafted.has(found.n)) return;
      // Use the actual pickNum (if provided) for the my-turn check so backfilled
      // older picks get attributed to the correct slot, not the current pickNum.
      const pickNumForCheck = msg.pickNum || state.pickNum;
      const inferredMine = (msg.mine !== undefined) ? !!msg.mine : isMyTurn(pickNumForCheck, state.slot);
      state.drafted.add(found.n);
      if (inferredMine) state.myRoster.push(found);
      state.history.push({ name: found.n, mine: inferredMine, prevPick: pickNumForCheck });
      // Only advance pickNum forward — never regress on a backfilled older pick.
      if (msg.pickNum) {
        if (msg.pickNum + 1 > state.pickNum) state.pickNum = msg.pickNum + 1;
      } else {
        state.pickNum += 1;
      }
      state.mode = "live";
      render();

      // v0.9.13: when a draft locks in (last pick made), auto-sync the
      // portfolio so the user's exposure %, stack, and need signals reflect
      // the just-completed draft on the next draft they enter. Triggers
      // once per draft via state.draftCompleteSynced.
      if (msg.pickNum === TOTAL_PICKS && !state.draftCompleteSynced) {
        state.draftCompleteSynced = true;
        console.log('[MFF] draft complete — auto-syncing portfolio in 5s');
        setTimeout(() => {
          if (typeof syncPortfolioFromUnderdog === 'function') {
            syncPortfolioFromUnderdog();
          }
        }, 5000); // delay so Underdog's API has time to flush the final pick
      }
    }
  }

  // Nickname/spelling differences between Underdog's names and our board
  // ("Kenny Gainwell" vs "Kenneth Gainwell"). The udN field normally covers
  // this, but ~25% of the pool has no UnderdogADP.csv match and therefore no
  // udN at all — those players fall through every match step and the pick
  // gets rejected as "not in pool". Keys are already norm()-shaped. Mirrors
  // ALIASES in export_sleeper_extension_data.py, applied in BOTH directions.
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

  // v0.9.97: accept an optional team abbreviation to disambiguate
  // initial+lastname inputs (e.g. "B. Robinson" → Bijan ATL vs Brian WAS).
  // The pick ribbon renders names as "F. Lastname" so without an
  // initial-aware fallback, every pick gets rejected as "not in pool".
  // v0.10.44: accept posHint too — primary disambiguator now, since FAs
  // in our data have t="FA" while UD reports their actual current team
  // (T. Hill WR/TE, K. Allen WR/RB collisions). Also: when team doesn't
  // match any candidate but exactly one is FA, prefer the FA — our data
  // is likely stale on their team after a signing.
  function findPlayerLoose(name, teamHint, posHint) {
    if (state.byName.has(name)) return state.byName.get(name);
    const stripSuffix = (n) => n.replace(/\s+(jr\.?|sr\.?|iii|ii|iv|v)$/i, "");
    const norm = (n) => stripSuffix(n).toLowerCase().replace(/[.\-']/g, "").trim();
    const target = norm(name);
    // 1) full-name normalized match (existing behavior)
    const exact = state.players.find(p => norm(p.n) === target || (p.udN && norm(p.udN) === target));
    if (exact) return exact;

    // 1b) alias retry — same full-name comparison against the other spelling.
    // Runs before the initial+lastname fallback so an alias hit never has to
    // survive that path's ambiguity tie-breaks.
    for (const alt of ALIASES[target] || []) {
      const hit = state.players.find(p => norm(p.n) === alt || (p.udN && norm(p.udN) === alt));
      if (hit) return hit;
    }

    // 2) "F. Lastname" / "F.Lastname" / "F Lastname" fallback. Underdog's
    // pick ribbon abbreviates first names — without this, sidebar rejects
    // virtually every detected live pick as "not in pool".
    const initialMatch = stripSuffix(name).match(/^\s*([A-Z])\.?\s+([A-Za-z][A-Za-z'.\-\s]+?)\s*$/);
    if (initialMatch) {
      const initial = initialMatch[1].toLowerCase();
      const lastNameTarget = norm(initialMatch[2]);
      let candidates = state.players.filter(p => {
        const playerName = stripSuffix(p.n || "");
        const parts = playerName.split(/\s+/).filter(Boolean);
        if (parts.length < 2) return false;
        // First initial of the player's first name must match
        if (!parts[0] || parts[0][0].toLowerCase() !== initial) return false;
        // Joined "rest of name after first" must equal the lastNameTarget
        const rest = norm(parts.slice(1).join(" "));
        if (rest === lastNameTarget) return true;
        // Also accept just the very-last token matching (handles rare middle names)
        const last = norm(parts[parts.length - 1]);
        return last === lastNameTarget;
      });
      if (candidates.length === 1) return candidates[0];
      // Multi-candidate path. Try POS first (T. Hill WR/TE, K. Allen WR/RB),
      // then team, then FA-prefer. Each filter is non-destructive when it
      // would empty the candidate set — we only narrow if it leaves ≥1.
      if (candidates.length > 1 && posHint) {
        const posNorm = String(posHint).toUpperCase().trim();
        const posFiltered = candidates.filter(p => (p.s || "").toUpperCase() === posNorm);
        if (posFiltered.length >= 1) candidates = posFiltered;
        if (candidates.length === 1) return candidates[0];
      }
      if (candidates.length > 1 && teamHint) {
        const hintNorm = String(teamHint).toUpperCase().trim();
        const teamMatch = candidates.find(p => {
          const ab = (typeof teamAbbr === "function" ? teamAbbr(p.t) : "") || "";
          return ab.toUpperCase() === hintNorm;
        });
        if (teamMatch) return teamMatch;
        // No team match — common when an FA candidate's real team has
        // changed (our data still says "FA"). If exactly one candidate is
        // FA, prefer it.
        const faCandidates = candidates.filter(p => (p.t || "").toUpperCase() === "FA");
        if (faCandidates.length === 1) return faCandidates[0];
      }
      // No team hint or no narrowing — return single survivor if any
      if (candidates.length === 1) return candidates[0];
      // Last-ditch: if multiple candidates remain and one is the lowest-ADP,
      // prefer it (more likely to be the actually-drafted player). Treats
      // udA>=240 as "no signal".
      if (candidates.length > 1) {
        const ranked = candidates
          .filter(p => p.udA != null && p.udA < 240)
          .sort((a, b) => a.udA - b.udA);
        if (ranked.length) {
          console.warn("[MFF/findPlayer] ambiguous", name,
                       "(team=" + (teamHint||"") + ", pos=" + (posHint||"") + "): chose",
                       ranked[0].n, "by ADP from", candidates.map(p => p.n + "(" + (p.t||"") + "/" + (p.s||"") + ")").join(", "));
          return ranked[0];
        }
      }
    }
    if (typeof console !== "undefined" && console.debug) {
      console.debug("[MFF/findPlayer] miss", name,
                    "team=" + (teamHint||""), "pos=" + (posHint||""));
    }
    return undefined;
  }

  function simulateUntilMyTurn() {
    if (!state.slot) return { projectedSet: state.drafted, atPick: state.pickNum };
    const projected = new Set(state.drafted);
    let p = state.pickNum;
    let safety = 220;
    while (!isMyTurn(p, state.slot) && safety-- > 0 && p <= TOTAL_PICKS) {
      const pool = state.players
        .filter(x => !projected.has(x.n) && x.udA != null && x.udA < 240)
        .sort((a, b) => a.udA - b.udA);
      if (pool.length) projected.add(pool[0].n);
      p++;
    }
    return { projectedSet: projected, atPick: p };
  }

  // TOP 3 PICKS strip above the rec list. Ranks the scored pool by the
  // engine's roster-aware REC score (need/saturation + stack + tier cliff +
  // ADP wait fade + value pockets baked in) and shows the three best with
  // medal styling + reason chips, whatever sort the list itself is using.
  function renderTop3(allRecs) {
    const el = document.getElementById("mff-top3");
    if (!el) return;
    if (!allRecs || !allRecs.length) { el.innerHTML = ""; return; }
    const top3 = allRecs.slice().sort((a, b) => (b.recScore || 0) - (a.recScore || 0)).slice(0, 3);
    const MEDALS = ["#ffd166", "#c0c7d1", "#c9926b"];
    el.innerHTML = top3.map((r, i) => {
      const p = r.player;
      const chips = [];
      const stack = detectStack(p, state.myRoster);
      // v0.16.1: STACK NOW (urgent — QB completes an existing stack and his
      // ADP window is this pick) outranks the passive STACK chip.
      if (r.flags && r.flags.stackNow) chips.push('<span style="background:#713f12;color:#fbbf24;padding:0 4px;border-radius:2px;font-weight:700">STACK NOW</span>');
      else if (stack) chips.push('<span style="background:#1e3a5f;color:#58a7ff;padding:0 4px;border-radius:2px">STACK</span>');
      if (r.flags && r.flags.need) chips.push('<span style="background:#1e3a5f;color:#7dd3fc;padding:0 4px;border-radius:2px">NEED ' + r.flags.need.toUpperCase() + '</span>');
      if (r.flags && r.flags.tier) chips.push('<span style="background:#3b0764;color:#d8b4fe;padding:0 4px;border-radius:2px">' + (r.flags.tier.type === "cliff" ? "TIER!" : "TIER") + '</span>');
      if (r.flags && r.flags.wait) chips.push('<span style="background:#334155;color:#cbd5e1;padding:0 4px;border-radius:2px">WAIT</span>');
      for (const w of (r.why || [])) {
        if (w === "STEAL") chips.push('<span style="background:#14532d;color:#86efac;padding:0 4px;border-radius:2px">STEAL</span>');
        else if (w === "Value") chips.push('<span style="background:#164e63;color:#67e8f9;padding:0 4px;border-radius:2px">VALUE</span>');
      }
      return '<div class="mff-top3-row" data-search-name="' + p.n.replace(/"/g, "&quot;") + '" title="REC score ' + (r.recScore || 0) + ' (mult ' + (r.recMult || 1) + 'x) — click to search">'
        + '<span class="t3-medal" style="color:' + MEDALS[i] + '">' + (i + 1) + '</span>'
        + '<span class="t3-name">' + p.n + '</span>'
        + '<span class="t3-pos pos-' + (p.s || "").toLowerCase() + '">' + (p.s || "") + '</span>'
        + '<span class="t3-chips">' + chips.join(" ") + '</span>'
        + '<span class="t3-score" style="color:' + MEDALS[i] + '">' + (r.recScore != null ? r.recScore : "") + '</span>'
        + '</div>';
    }).join("");
    el.onclick = (e) => {
      const row = e.target.closest(".mff-top3-row");
      if (!row) return;
      const inp = document.getElementById("mff-search");
      if (inp) {
        inp.value = row.dataset.searchName || "";
        inp.dispatchEvent(new Event("input", { bubbles: true }));
        inp.focus();
      }
    };
  }

  function render() {
    const ENGINE = window.MFFEngine;
    if (!ENGINE) return;
    // Fire the turn alert on the *transition* into "my turn" — render() is
    // called on every state change, so this is the natural hook.
    maybeFireTurnAlert();
    // Persist any state change that landed before this render.
    persistState();
    const round = ENGINE.pickToRound(state.pickNum, TEAM_SIZE);
    const myTurn = isMyTurn(state.pickNum, state.slot);
    const until = picksUntilMyNext(state.pickNum, state.slot);
    // v0.9.12: compact pick info line (replaces the full STATUS section).
    const pickLine = document.getElementById("mff-pick-line");
    if (pickLine) {
      const untilStr = myTurn ? "NOW" : ("Next: " + until);
      pickLine.innerHTML =
        '<span class="pl-pick">Pick ' + state.pickNum + '/' + TOTAL_PICKS + '</span>' +
        '<span class="pl-sep">·</span>' +
        '<span class="pl-round">R' + round + '</span>' +
        '<span class="pl-sep">·</span>' +
        '<span class="pl-mine">' + state.myRoster.length + ' mine</span>' +
        '<span class="pl-sep">·</span>' +
        '<span class="pl-until' + (myTurn ? ' on-clock' : '') + '">' + untilStr + '</span>';
    }
    // Legacy STATUS elements (now removed) — guarded so any orphaned refs no-op.
    const elPick = document.getElementById("s-pick");
    if (elPick) elPick.textContent = state.pickNum + "/" + TOTAL_PICKS;
    const elRound = document.getElementById("s-round");
    if (elRound) elRound.textContent = round;
    const elMine = document.getElementById("s-mypicks");
    if (elMine) elMine.textContent = state.myRoster.length;
    const elUntil = document.getElementById("s-until");
    if (elUntil) elUntil.textContent = myTurn ? "NOW" : until;

    const counts = ENGINE.rosterCounts(state.myRoster);
    // v0.9.11: top row (r-*) now shows the OPTIMAL/TARGET counts; bottom row
    // (t-*) shows REMAINING (target - current). The user wanted to see at a
    // glance what they should aim for vs. what they still need to fill.
    const targets = recommendedRoster(state.myRoster, state.isSuperflex, TEAM_SIZE);

    for (const pos of ["QB", "RB", "WR", "TE"]) {
      // Top row: target values, position-colored.
      const tEl = document.getElementById("r-" + pos);
      if (tEl) {
        tEl.textContent = targets[pos] || 0;
        tEl.style.color = '#ffd166'; // gold for target values
      }

      // Bottom row: remaining = max(0, target - have).
      const rEl = document.getElementById("t-" + pos);
      if (rEl) {
        const have = counts[pos] || 0;
        const remaining = Math.max(0, (targets[pos] || 0) - have);
        rEl.textContent = remaining;
        // Color: green when filled (0 left), amber when 1-2 left, red when 3+.
        rEl.style.color = '';
        if (remaining === 0) rEl.style.color = '#22c55e';     // done
        else if (remaining <= 2) rEl.style.color = '#f59e0b'; // close
        else rEl.style.color = '#ef4444';                     // still a lot
      }
    }

    // v0.9.78: BBM advance-rate badge + per-position next-pick rates
    try { _renderBbmAdvance(state, counts, targets); } catch (e) { console.warn('[MFF BBM]', e); }
    // Live next-pick advance rate by position (uses BBM_PICK_BY_RANK_ROUND).
    try { renderNextPickRates(); } catch (e) { console.warn('[MFF nextpick]', e); }
    // Construction checklist — year-stable structural rules from 2.0M-team BBM aggregation
    try { renderConstructionChecklist(); } catch (e) { console.warn('[MFF check]', e); }
    // Projections tab — re-renders only when visible (cheap no-op otherwise).
    try { renderProjections(); } catch (e) { console.warn('[MFF projections]', e); }

    // v0.9.67: pass players + drafted so rosterReport can compute
    // vorByPos (banked) AND bestAvail (best VOR available per position).
    const report = ENGINE.rosterReport(state.myRoster, state.pickNum, TEAM_SIZE, state.isSuperflex, state.players, state.drafted);
    const flagsEl = document.getElementById("mff-flags");
    flagsEl.innerHTML = "";
    for (const f of report.flags) {
      const d = document.createElement("div");
      d.className = "mff-flag " + f.level;
      d.textContent = f.msg;
      flagsEl.appendChild(d);
    }
    // v0.9.68: full position-level analysis. Combines VOR scarcity
    // (now vs next pick assuming opponents draft by rank), slot need,
    // and roster banked balance. Drives both the per-position cells
    // and the suggested-position line below.
    let posAnalysis = null;
    let posSuggestion = null;
    try {
      posAnalysis = ENGINE.analyzePositions(
        state.myRoster, state.players, state.drafted,
        state.pickNum, state.slot || 6, TEAM_SIZE, state.isSuperflex
      );
      posSuggestion = ENGINE.suggestPosition(posAnalysis);
    } catch (e) { /* no-op */ }

    // Render banked VOR + dropoff per position.
    if (report.vorByPos) {
      const posColors = { QB: "#ef4444", RB: "#22c55e", WR: "#3b82f6", TE: "#f59e0b" };
      const recommendedPos = posSuggestion ? posSuggestion.pos : null;
      for (const pos of ["QB", "RB", "WR", "TE"]) {
        const el = document.getElementById("v-" + pos);
        if (!el) continue;
        const v = Math.round(report.vorByPos[pos] || 0);
        const have = report.counts[pos] || 0;
        const valStr = (v > 0 ? "+" : "") + v;
        const valColor = v > 0 ? "#e5e7eb" : "#6b7280";

        // Scarcity indicator from posAnalysis: bestNow + dropoff to next pick.
        let scarcity = "";
        const a = posAnalysis && posAnalysis.positions[pos];
        if (a && a.bestNow != null) {
          const drop = a.dropoff != null ? a.dropoff : 0;
          const dropArrow = drop >= 30 ? '<span style="color:#ef4444"> ↓' + drop + '</span>'
                          : drop >= 15 ? '<span style="color:#facc15"> ↓' + drop + '</span>'
                          :              '';
          // Show "next +X" when no players banked yet, otherwise keep compact
          if (have === 0 && a.bestNow > -500) {
            scarcity = ' <span style="color:#94a3b8">(now ' + (a.bestNow >= 0 ? '+' : '') + Math.round(a.bestNow) + ')</span>' + dropArrow;
          } else if (drop >= 15) {
            // Even with players banked, surface a big dropoff
            scarcity = dropArrow;
          }
        }

        // Highlight recommended position with a subtle yellow background
        const bg = (pos === recommendedPos)
          ? "background:rgba(251,191,36,0.16);padding:1px 6px;border-radius:4px;"
          : "";

        el.innerHTML = '<span style="' + bg + '"><span style="color:' + posColors[pos] + '">' + pos + '</span> '
          + '<span style="color:' + valColor + ';font-weight:600">' + valStr + '</span>'
          + scarcity + '</span>';
      }
    }

    // Render the "Suggested: X" line above the recs.
    const suggestEl = document.getElementById("mff-pos-suggest");
    if (suggestEl) {
      if (posSuggestion) {
        const reasons = posSuggestion.reasons.length
          ? ' <span style="color:#94a3b8">— ' + posSuggestion.reasons.join('; ') + '</span>'
          : '';
        suggestEl.innerHTML = '<span style="color:#94a3b8">→ Suggested:</span> '
          + '<span style="color:#fbbf24;font-weight:700">' + posSuggestion.pos + '</span>'
          + reasons;
      } else {
        suggestEl.innerHTML = '';
      }
    }

    try { renderValueChart(); } catch (e) { console.warn('[MFF valuechart]', e); }

    // Always show best available based on the current draft state — never
    // simulate forward to the user's next pick. Header says "On the Clock"
    // when it's actually the user's turn, otherwise just "Best Available".
    // Bump topN when a position filter is active so the user still sees a full
    // list within that position even if those players are spread across the
    // top of the board.
    const isFiltered = state.posFilter && state.posFilter !== "ALL";
    // v0.10.54: REC mode widens the candidate pool (60 by rank) so a
    // boosted stack/need player sitting just outside the top 30 can still
    // surface after re-scoring; the displayed list is trimmed back to 30.
    const allRecs = ENGINE.recommend({
      players: state.players, draftedSet: state.drafted, myRoster: state.myRoster,
      pickNum: state.pickNum, slot: state.slot || 6, teamSize: TEAM_SIZE,
      topN: isFiltered ? 120 : (state.sortBy === "rec" ? 60 : 30),
      rankSrc: state.rankSrc,
      isSuperflex: state.isSuperflex,
      mode: state.isRedraft ? "rd" : "bb",
    });
    let recs = isFiltered
      ? allRecs.filter(r => r.player && r.player.s === state.posFilter).slice(0, 20)
      : allRecs;

    // TOP 3 PICKS strip — always ordered by the roster-aware REC score
    // (rank base × need/saturation × stack × tier cliff × ADP wait fade ×
    // value-pocket mult), independent of the list's sort mode, so the
    // "what should I actually take" answer is always on screen.
    try { renderTop3(allRecs); } catch (e) { console.warn('[MFF top3]', e); }
    // v0.9.90: optional re-sort by VOR (descending). Player vor varies by
    // standard vs SF format; uses ENGINE.playerVor which respects state.isSuperflex.
    if (state.sortBy === "vor" && ENGINE.playerVor) {
      recs = recs.slice().sort((a, b) => {
        const va = ENGINE.playerVor(a.player, state.isSuperflex);
        const vb = ENGINE.playerVor(b.player, state.isSuperflex);
        const aVal = (va == null) ? -99999 : va;
        const bVal = (vb == null) ? -99999 : vb;
        return bVal - aVal;
      });
    }
    // v0.10.54: REC sort — roster-aware score from engine.js scorePlayer:
    // rank base × stack boost (up to 1.12x) × need boost (up to 1.15x) ×
    // loaded-position nerf (down to 0.82x soft / 0.25x at hard cap).
    if (state.sortBy === "rec") {
      recs = recs.slice().sort((a, b) => (b.recScore || 0) - (a.recScore || 0));
      if (!isFiltered) recs = recs.slice(0, 30);
    }

    // The "Best Available" / "On the Clock" header was removed in v0.9.0.
    // The "Until next: NOW" indicator in the status row + the turn-alert beep
    // already convey on-the-clock state, and the dropdowns above the recs
    // make the section's purpose obvious.
    const recsEl = document.getElementById("mff-recs");
    recsEl.innerHTML = "";
    if (isFiltered && !recs.length) {
      const empty = document.createElement("div");
      empty.style.cssText = "padding:14px;text-align:center;color:#8a8d96;font-size:11px;font-style:italic";
      empty.textContent = "No " + state.posFilter + "s left in the top of the board.";
      recsEl.appendChild(empty);
    }

    // v0.9.86: BBM-recommended position drives the gold .top highlight.
    // Previously highlighted whoever was idx===0 (just rank #1 by Jack's
    // rankings). Now: find the highest-ranked player at the position the
    // BBM optimizer recommends to take next, and highlight THAT one.
    let _bbmTopIdx = 0; // fallback: idx 0
    let _bbmRecPos = null;
    try {
      const _counts = ENGINE.rosterCounts(state.myRoster);
      const _drafted = state.myRoster ? state.myRoster.length : 0;
      if (_drafted < 18 && window.MFFEngine.bbmNextPickRates && window.BBM_DATA) {
        const _prefix = (state.myRoster || []).slice(0, 6).map(function(p){
          return (p.s || '').charAt(0).toUpperCase();
        }).filter(function(c){ return c==='Q'||c==='R'||c==='W'||c==='T'; }).join('');
        const _rates = window.MFFEngine.bbmNextPickRates(_counts, state.slot, _drafted, { prefix: _prefix });
        if (_rates && _rates.recommended) {
          _bbmRecPos = _rates.recommended;
          // Find highest-ranked player at that position in the displayed list
          for (let _i = 0; _i < recs.length; _i++) {
            if (recs[_i].player && recs[_i].player.s === _bbmRecPos) { _bbmTopIdx = _i; break; }
          }
        }
      }
    } catch (_e) { /* fall back to idx 0 */ }

    // v0.10.0: precompute per-rec BBM lift inputs once. Each card gets a
    // tournament-equity blended lift badge (50/30/20 QF/SF/Finals) showing
    // how taking THIS player at the user's current pick historically
    // affected advance rate. Uses BBM_PICK_BY_RANK_ROUND (STD-only). For
    // Superflex drafts the lift badge is suppressed (BBM data doesn't apply).
    const _liftRound = Math.max(1, Math.min(18, Math.ceil((state.pickNum || 1) / 12)));
    const _liftCounts = ENGINE.rosterCounts(state.myRoster);
    const _liftEnabled =
      !state.isSuperflex && !state.isRedraft &&
      typeof BBM_PICK_BY_RANK_ROUND !== 'undefined' &&
      typeof BBM_BASELINE_QF_RATE !== 'undefined';
    const _liftBaseQf = _liftEnabled ? BBM_BASELINE_QF_RATE : 0.16668;
    const _liftBaseSf = (typeof BBM_BASELINE_SF_RATE !== 'undefined') ? BBM_BASELINE_SF_RATE : 0.01320;
    const _liftBaseFin = (typeof BBM_BASELINE_FIN_RATE !== 'undefined') ? BBM_BASELINE_FIN_RATE : 0.00082;
    function _bbmLiftFor(pos) {
      if (!_liftEnabled || !pos) return null;
      const tbl = BBM_PICK_BY_RANK_ROUND[pos.toLowerCase()];
      if (!tbl) return null;
      const nextRank = (_liftCounts[pos] || 0) + 1;
      const cell = tbl[nextRank] && tbl[nextRank][_liftRound];
      if (!cell || cell.qf == null) return null;
      const qL = cell.qf / _liftBaseQf;
      const sL = (cell.sf != null) ? cell.sf / _liftBaseSf : qL;
      const fL = (cell.fin != null) ? cell.fin / _liftBaseFin : qL;
      return { lift: 0.50 * qL + 0.30 * sL + 0.20 * fL, nextRank: nextRank };
    }

    // Jack's-tier separators: only while the list IS Jack's board order.
    const _showTierSeps = state.sortBy === "rank" && state.rankSrc === "jacks" && !!jackTierList();
    let _lastTierLabel = null;
    recs.forEach((r, idx) => {
      const p = r.player;
      const _jkTier = state.rankSrc === "jacks" ? jackTierFor(jackTierRank(p)) : null;
      if (_showTierSeps && _jkTier && _jkTier.l !== _lastTierLabel) {
        const _tc = jackTierColor(_jkTier.l);
        const sepEl = document.createElement("div");
        sepEl.className = "mff-tier-sep";
        sepEl.style.color = _tc;
        sepEl.style.borderColor = _tc;
        sepEl.innerHTML = '<span class="mff-tier-sep-badge" style="background:' + _tc + '">' + _jkTier.l + '</span>'
          + ((_jkTier.n || ('TIER ' + _jkTier.l)).replace(/[<>&]/g, ''));
        recsEl.appendChild(sepEl);
        _lastTierLabel = _jkTier.l;
      }
      const stack = detectStack(p, state.myRoster);
      // v0.9.74: TEAM is a softer correlation. Only surface when no STACK is
      // present — STACK takes precedence since QB-skill correlation is the
      // stronger signal.
      // v0.9.88: STACK overrides both TEAM and NEED. The QB-stack signal is
      // the strongest historical correlator with advance rate (1.21x lift on
      // full2 stacks), so when present it should not be diluted by softer
      // NEED highlights. Hierarchy: STACK > TEAM > NEED.
      const team = stack ? null : detectTeam(p, state.myRoster);
      const counts = ENGINE.rosterCounts(state.myRoster);
      const needFlag = (stack || team)
        ? null
        : (typeof window.MFFEngine_detectNeed === "function"
            ? window.MFFEngine_detectNeed(p.s, counts, round, state.isSuperflex, TEAM_SIZE)
            : null);
      const div = document.createElement("div");
      div.className = "mff-rec"
        + (idx === _bbmTopIdx ? " top" : "")
        + (stack ? " stack" : "")
        + (team ? " team" : "")
        + (needFlag ? " need need-" + needFlag : "");
      // v0.9.67 TIER cliff: VOR drop ≥30 to next 3 same-position picks =
      // urgent "take now" signal; ≥18 = soft cliff. Render in why-tag area
      // so it stands alongside STEAL / Value / Reach tags.
      const _tierInfo = r.flags && r.flags.tier;
      const tierTag = _tierInfo
        ? '<span class="tag" style="background:#a855f7;color:#fff;font-weight:700" title="VOR drops ' + _tierInfo.drop + ' to the next 3 ' + p.s + 's — tier cliff">' + (_tierInfo.type === 'cliff' ? 'TIER!' : 'TIER') + '</span>'
        : '';
      // v0.10.55: WAIT tag (REC mode only) — ADP says this player likely
      // lasts until the user's next turn, so REC faded him out of the top spot.
      const waitTag = (state.sortBy === "rec" && r.flags && r.flags.wait)
        ? '<span class="tag" style="background:#475569;color:#cbd5e1" title="ADP says this player likely goes after your next pick — REC fades him (' + r.flags.wait.toFixed(2) + 'x) so you can take scarcer value now and circle back">WAIT</span>'
        : '';
      const tags = waitTag + tierTag + r.why
        .filter(w => w !== 'TIER' && w !== 'TIER!')
        .map(w => '<span class="tag ' + w + '">' + w + '</span>').join("");
      const stackBadge = stack
        ? '<span class="stack-badge">★ STACK ' + (stack.kind === "qb-stack"
            ? "with " + stack.with.map(x => x.n.split(" ").pop()).join(", ")
            : "with " + stack.with[0].n.split(" ").pop()) + '</span>'
        : team
          ? '<span class="team-badge" style="background:#cbd5e1;color:#1e293b;padding:1px 5px;border-radius:3px;font-size:9px;font-weight:700;letter-spacing:.4px">TEAM '
              + team.with.map(x => x.n.split(" ").pop()).join(", ") + '</span>'
          : "";
      const ppg = (p.pPg != null) ? p.pPg.toFixed(1) : "—";
      // v0.9.73: try udN as a fallback so Jr/Sr/III variants match.
      const _percentMap = state.portfolio && state.portfolio.percent;
      const _percentKey = _portfolioKey(p, _percentMap);
      const portfolio = (_percentMap && _percentKey != null && _percentMap[_percentKey] != null)
        ? _percentMap[_percentKey].toFixed(0) + "%"
        : "—";
      // v0.9.65 VOR badge — half-PPR season-pts marginal value above
      // replacement-level. v0.9.67: format-aware — uses vor/up for standard
      // (QB12/RB30/WR42/TE13), vorSf/upSf for superflex (QB24/RB30/WR30/TE13).
      // Late QBs jump ~+45 in SF, late WRs drop ~-18 in SF.
      const _isSf = !!state.isSuperflex;
      const _vorRaw = _isSf ? p.vorSf : p.vor;
      const vorVal = (_vorRaw != null && !isNaN(_vorRaw)) ? Math.round(_vorRaw) : null;
      const vorColor = vorVal == null ? "#94a3b8" :
                       vorVal >= 80 ? "#22c55e" :
                       vorVal >= 40 ? "#4ade80" :
                       vorVal >= 10 ? "#facc15" :
                       vorVal >= -10 ? "#94a3b8" :
                                        "#ef4444";
      const vorStr = vorVal == null ? "—" : (vorVal > 0 ? "+" : "") + vorVal;
      const _vorTitle = _isSf
        ? "Superflex VOR — half-PPR season pts above QB24/RB30/WR30/TE13 cutoffs"
        : "Value Over Replacement — half-PPR season pts above QB12/RB30/WR42/TE13 cutoffs";
      const vorSpan = '<span style="color:' + vorColor + ';font-weight:700" title="' + _vorTitle + '">VOR ' + vorStr + '</span>';
      // UP badge — ceiling-PPG advantage. Same format toggle as VOR.
      const _upRaw = _isSf ? p.upSf : p.up;
      const upVal = (_upRaw != null && !isNaN(_upRaw)) ? _upRaw : null;
      const upColor = upVal == null ? "#94a3b8" :
                      upVal >= 5  ? "#22c55e" :
                      upVal >= 2  ? "#4ade80" :
                      upVal >= 0  ? "#facc15" :
                      upVal >= -3 ? "#94a3b8" :
                                     "#ef4444";
      const upStr = upVal == null ? "—" : (upVal > 0 ? "+" : "") + upVal.toFixed(1);
      const upSpan = '<span style="color:' + upColor + ';font-weight:700" title="Ceiling-PPG advantage vs replacement: how much better a boom week is than the freely available alternative. Late-round dart throws with high UP are good upside swings. For RB/WR, includes probability-weighted handcuff equity.">↑' + upStr + '</span>';
      // v0.9.66 HC badge — handcuff / elevation upside for RB/WR backups.
      // Shows when there's significant role to inherit if their team's lead
      // at that position misses time. Calibrated lift: RB next-up captures
      // ~65% of lost workload, WR next-up captures ~55% of redistributed
      // targets. CMC's backup → big HC; Commanders RB3 → small HC.
      const hcVal = (p.hcPpg != null && p.pPg != null) ? p.hcPpg - p.pPg : 0;
      const hcSpan = (hcVal >= 3.0)
        ? '<span style="color:#a855f7;font-weight:700" title="Handcuff equity: +' + hcVal.toFixed(1) + ' PPG if elevated to lead at their position (RB1 injury / WR1 absorption). Already factored into the UP metric.">HC +' + hcVal.toFixed(1) + '</span>'
        : '';
      // v0.10.0: BBM LIFT badge — per-pick historical advance-rate effect of
      // taking this position at this round (tournament-equity blend). Reach
      // detector kicks in below 0.85; value flag at 1.10+.
      let liftSpan = '';
      const _liftInfo = _bbmLiftFor(p.s);
      if (_liftInfo != null) {
        const _L = _liftInfo.lift;
        const _liftCol = _L >= 1.10 ? '#22c55e'
                       : _L >= 1.00 ? '#86efac'
                       : _L >= 0.90 ? '#94a3b8'
                       : _L >= 0.85 ? '#f59e0b'
                       : '#ef4444';
        const _liftPct = Math.round((_L - 1) * 100);
        const _liftStr = (_liftPct >= 0 ? '+' : '') + _liftPct + '%';
        const _isReach = _L < 0.85;
        const _isValue = _L >= 1.10;
        const _flagPrefix = _isValue ? '★ ' : _isReach ? '⚠ ' : '';
        const _liftTitle = 'BBM advance-rate lift: ' + _L.toFixed(2) + 'x baseline taking ' + p.s + _liftInfo.nextRank +
                          ' at R' + _liftRound + ' (50/30/20 QF/SF/Finals blend)' +
                          (_isValue ? ' — historical VALUE pick' :
                           _isReach ? ' — historical REACH, sub-baseline at this round' : '');
        liftSpan = '<span style="color:' + _liftCol + ';font-weight:700" title="' + _liftTitle.replace(/"/g,'&quot;') + '">' + _flagPrefix + _liftStr + '</span>';
      }
      // Badge moves to the top-right corner of the card (above the projection
      // score) — keeps the name line clean and stops STACK/TEAM tags from
      // pushing the name into ellipsis territory on long names.
      const nameHtml = '<div class="name">' + p.n + '</div>';
      const cornerBadgeHtml = stackBadge
        ? '<div class="mff-corner-badge">' + stackBadge + '</div>'
        : '';
      // Inline ADP-movement indicator. Shows next to the UD ADP value on
      // every rec card so the user can see at a glance which players have
      // been climbing/falling without expanding the profile. Mirrors the
      // logic in the Underdog row decorator and the expanded profile.
      let udAdpHtml = '';
      if (p.udA != null) {
        let mvtHtml = '';
        try {
          const fmt = state.isSuperflex ? 'sf' : 'bbm';
          const winDays = state.adpWindow || 7;
          const cur = (fmt === 'sf' ? p.sfa : p.udA);
          if (cur != null && state.adpHistory && state.adpHistory.length) {
            const mvt = _computeAdpDelta(p.n, cur, winDays, state.adpHistory, fmt);
            if (mvt && Math.abs(mvt.delta) >= 0.1) {
              const rising = mvt.delta > 0;
              const color = rising ? '#16a34a' : '#dc2626';
              const arrow = rising ? '▲' : '▼';
              const tip = (rising ? 'ADP rose ' : 'ADP fell ') +
                          Math.abs(mvt.delta).toFixed(1) + ' over ' + winDays +
                          ' days (was ' + mvt.oldAdp.toFixed(1) +
                          ' on ' + mvt.oldDate + ')';
              mvtHtml = ' <span style="color:' + color + ';font-weight:700" title="' +
                        tip + '">' + arrow + Math.abs(mvt.delta).toFixed(1) + '</span>';
            }
          }
        } catch (_) { /* swallow — never block render on movement calc */ }
        udAdpHtml = '<span>UD ' + p.udA + mvtHtml + '</span>';
      }
      // v0.10.16: Playoff matchups (BBM weeks 15-17). Show 3 inline pills
      // with opp abbr + home/away, colored by per-week SOS rating for this
      // player's position. Skips K/DST (and any pos not in our lookup) and
      // skips players without a recognizable NFL team.
      let playoffMatchupsHtml = '';
      if ((p.s === 'QB' || p.s === 'RB' || p.s === 'WR' || p.s === 'TE')
          && typeof window.MFF_PLAYOFF_SOS === 'object') {
        const _tAbbr = teamAbbr(p.t);
        const _teamRec = _tAbbr ? window.MFF_PLAYOFF_SOS[_tAbbr] : null;
        const _posRec = _teamRec ? _teamRec[p.s] : null;
        if (_posRec) {
          const _pills = [15, 16, 17].map(w => {
            const m = _posRec[w];
            if (!m) return '';
            const _arrow = m.home ? 'vs' : '@';
            const _host = _hostAbbr(_tAbbr, m);
            const _isDome = _host && DOME_TEAMS.has(_host);
            const _tt = 'W' + w + ' ' + _arrow + ' ' + m.opp +
                        ' — ' + (m.label === 'E' ? 'easy' : m.label === 'M' ? 'mid' : 'hard') +
                        ' (rank ' + m.rank + '/32 for ' + p.s + ')' +
                        (typeof m.gameTotal === 'number' ? ', O/U ' + m.gameTotal : '') +
                        (typeof m.teamSpread === 'number' ? ', ' + (m.teamSpread > 0 ? '+' : '') + m.teamSpread + ' spread' : '') +
                        (_isDome ? ' · dome (' + _host + ')' : '');
            return '<span style="color:' + m.color + ';font-weight:700" title="' + _tt.replace(/"/g, '&quot;') + '">' +
                   'W' + w + ' ' + _arrow + m.opp + (_isDome ? ' Ⓓ' : '') + '</span>';
          }).join('');
          if (_pills) {
            playoffMatchupsHtml =
              '<div class="meta" style="margin-top:2px;font-size:10px;opacity:.95" title="Playoff matchups · color by ' + p.s + ' SOS rank">' +
                '<span style="color:#94a3b8;font-size:9px;letter-spacing:.5px">PLAYOFFS</span>' +
                _pills +
              '</div>';
          }
        }
      }
      // v0.10.58: manual "mark drafted" ✕ — corrects the board when a live
      // pick was missed (e.g. FA cards the ribbon scanner failed to parse).
      const removeBtnHtml =
        '<button class="mff-rec-remove" title="Mark as drafted by another team (remove from board). Use when a pick was missed — e.g. free agents." ' +
        'style="position:absolute;right:3px;bottom:2px;background:none;border:none;color:#64748b;font-size:10px;cursor:pointer;padding:2px 4px;line-height:1;opacity:.55">✕</button>';
      div.innerHTML = '' +
        cornerBadgeHtml +
        removeBtnHtml +
        '<div class="num">' + (idx + 1) + '</div>' +
        '<div class="info">' +
          nameHtml +
          '<div class="meta">' +
            '<span class="pos ' + p.s + '">' + p.s + '</span>' +
            '<span>' + teamAbbr(p.t) + '</span>' +
            '<span>R#' + p.rank + (_jkTier ? ' <b class="mff-jtier" style="color:' + jackTierColor(_jkTier.l) + '" title="Jack\'s tier: ' + (_jkTier.n || _jkTier.l).replace(/[<>&"]/g, '') + '">' + _jkTier.l + '</b>' : '') + '</span>' +
            udAdpHtml +
            '<span>PPG ' + ppg + '</span>' +
            '<span>Port ' + portfolio + '</span>' +
            vorSpan +
            upSpan +
            hcSpan +
            liftSpan +
          '</div>' +
          playoffMatchupsHtml +
          '<div class="why">' + tags + '</div>' +
        '</div>' +
        '<div class="score">' + r.score + '</div>';
      div.addEventListener("click", () => toggleProfile(div, p, stack));
      const _rmBtn = div.querySelector(".mff-rec-remove");
      if (_rmBtn) {
        _rmBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          if (state.drafted.has(p.n)) return;
          state.drafted.add(p.n);
          // prevPick = current pick → "Undo Last" restores cleanly without
          // touching pickNum (this is a correction, not an observed pick).
          state.history.push({ name: p.n, mine: false, prevPick: state.pickNum });
          console.log("[MFF] manually marked drafted:", p.n);
          render();
        });
      }
      recsEl.appendChild(div);
      // If this player's profile was open before this render, re-attach it so
      // background re-renders (storage changes, new picks, etc.) don't snap
      // the card closed.
      if (state.expandedRec === p.n) {
        div.appendChild(buildProfileEl(p, stack));
      }
    });

    // Mode badge was removed in v0.8.7 — the panel only operates in LIVE mode now.
    const badge = document.getElementById("mff-mode-badge");
    if (badge) {
      badge.className = "badge " + state.mode;
      badge.textContent = state.mode.toUpperCase();
    }

    // v0.9.4: roster/slot/format may have changed → STACK & NEED signals
    // need to recompute on the Underdog player list. Cheap: just clears
    // the badges and queues a rescan.
    if (typeof refreshDecorations === "function") refreshDecorations();
  }

  // Build the expanded profile DOM for a player. Pure — no side effects.
  function buildProfileEl(p, stack) {
    const ppg = (p.pPg != null) ? p.pPg.toFixed(1) : "—";
    const lastPpg = (p.p25 != null) ? p.p25.toFixed(1) : "—";
    const udVal = (p.udA != null) ? p.udA : "—";
    const ageStr = p.age != null ? p.age : "—";
    // v0.9.73: try udN as a fallback so Jr/Sr/III variants match.
    const _percentMap = state.portfolio && state.portfolio.percent;
    const _percentKey = _portfolioKey(p, _percentMap);
    const portfolio = (_percentMap && _percentKey != null && _percentMap[_percentKey] != null)
      ? _percentMap[_percentKey].toFixed(1) + "%"
      : "—";
    // v0.9.74: include TEAM info in the profile header when no STACK applies.
    const team = stack ? null : detectTeam(p, state.myRoster);
    const stackText = stack
      ? (stack.kind === "qb-stack"
          ? "Pairs with: " + stack.with.map(x => x.n).join(", ")
          : "Pairs with QB: " + stack.with[0].n)
      : (team
          ? "Same team as: " + team.with.map(x => x.n).join(", ")
          : "");
    const adpVsRank = (p.udA != null && p.rank)
      ? (p.udA - p.rank > 0 ? "+" + (p.udA - p.rank).toFixed(1) : (p.udA - p.rank).toFixed(1))
      : "—";
    let coRows = "";
    if (state.myRoster.length) {
      const pairs = state.portfolio && state.portfolio.pairs;
      const counts = state.portfolio && state.portfolio.counts;
      // v0.9.73: resolve the rec player's portfolio name (n vs udN) once.
      // Pairs are keyed by the UD-name pair, so we need the key that
      // actually exists in counts.
      const pKey = _portfolioKey(p, counts) || p.n;
      const totalWithThis = counts ? counts[pKey] : null;
      const lines = [];
      for (const r of state.myRoster) {
        if (!pairs || !counts || !totalWithThis) {
          lines.push('<div class="prof-row"><span class="k">w/ ' + r.n + '</span><span class="v">—</span></div>');
        } else {
          // myRoster entries already use the same name format as pairs
          // (both come from UD picks), so r.n matches as-is.
          const k1 = pKey + "|" + r.n;
          const k2 = r.n + "|" + pKey;
          const both = (pairs[k1] || 0) + (pairs[k2] || 0);
          const pct = totalWithThis > 0 ? (100 * both / totalWithThis) : 0;
          lines.push('<div class="prof-row"><span class="k">w/ ' + r.n + '</span><span class="v">' + pct.toFixed(0) + '%</span></div>');
        }
      }
      coRows = '<div class="prof-divider">Roster co-occurrence</div>' + lines.join("");
    }
    const div = document.createElement("div");
    div.className = "mff-profile";
    // Stop click events inside the profile from bubbling up to the card and
    // re-toggling it. The profile itself isn't interactive; this just keeps
    // accidental clicks on the body of the profile from closing it.
    div.addEventListener("click", (e) => e.stopPropagation());
    div.innerHTML = '' +
      '<div class="prof-row"><span class="k">Position</span><span class="v">' + p.s + ' — ' + (p.t || "") + '</span></div>' +
      '<div class="prof-row"><span class="k">Jack\'s rank</span><span class="v">#' + p.rank +
        (function () { const t = jackTierFor(jackTierRank(p)); return t ? ' · ' + (t.n || 'Tier ' + t.l).replace(/[<>&]/g, '') : ''; })() + '</span></div>' +
      '<div class="prof-row"><span class="k">Underdog ADP</span><span class="v">' + udVal + (function(){
        // v0.9.69: inline movement indicator on the ADP row.
        try {
          const fmt = state.isSuperflex ? 'sf' : 'bbm';
          const winDays = state.adpWindow || 7;
          const cur = (fmt === 'sf' ? p.sfa : p.udA);
          if (cur == null || !state.adpHistory || !state.adpHistory.length) return '';
          const mvt = _computeAdpDelta(p.n, cur, winDays, state.adpHistory, fmt);
          if (!mvt || Math.abs(mvt.delta) < 0.1) return '';
          const rising = mvt.delta > 0;
          const color = rising ? '#16a34a' : '#dc2626';
          const arrow = rising ? '▲' : '▼';
          return ' <span style="color:' + color + ';font-weight:700;font-size:11px;margin-left:4px" title="' +
                 (rising ? 'Rose' : 'Fell') + ' ' + Math.abs(mvt.delta).toFixed(1) +
                 ' over ' + winDays + ' days (was ' + mvt.oldAdp.toFixed(1) + ' on ' + mvt.oldDate + ')">' +
                 arrow + ' ' + Math.abs(mvt.delta).toFixed(1) + '</span>';
        } catch (_) { return ''; }
      })() + '</span></div>' +
      '<div class="prof-row"><span class="k">ADP vs rank</span><span class="v">' + adpVsRank + '</span></div>' +
      '<div class="prof-row"><span class="k">Last yr PPG</span><span class="v">' + lastPpg + '</span></div>' +
      '<div class="prof-row"><span class="k">Proj PPG (1/2 PPR)</span><span class="v">' + ppg + '</span></div>' +
      '<div class="prof-row"><span class="k">Age</span><span class="v">' + ageStr + '</span></div>' +
      '<div class="prof-row"><span class="k">Portfolio %</span><span class="v">' + portfolio + '</span></div>' +
      (stackText ? '<div class="prof-row stack"><span class="k">Stack</span><span class="v">' + stackText + '</span></div>' : "") +
      coRows;
    return div;
  }

  function toggleProfile(card, p, stack) {
    const existing = card.querySelector(".mff-profile");
    if (existing) {
      existing.remove();
      state.expandedRec = null;
      return;
    }
    document.querySelectorAll(".mff-profile").forEach(el => el.remove());
    state.expandedRec = p.n;
    card.appendChild(buildProfileEl(p, stack));
  }

  // Recommended final roster size per position. Adapts to:
  //  1. Format (Best Ball vs Superflex) — different default targets.
  //  2. Your drafting tendency — once you've made 4+ picks, the targets
  //     skew toward your observed positional ratio. If you're hammering
  //     RB early, the target nudges up at RB and down at WR; same logic
  //     in reverse for WR-heavy starts.
  //  3. Floors / ceilings — never recommends fewer at a position than
  //     you've already drafted, and respects format min/max.
  // Returns { QB, RB, WR, TE } summing roughly to (rounds-1) — leaves a
  // little headroom for K/DST or extra depth at the user's discretion.
  // Roster Construction Checklist. Live-updates on every render. Renders a
  // small list of pass/fail items derived from 2.0M-team BBM IV/V/VI history.
  // Each rule is year-stable (mechanical/structural, not personnel-driven):
  //   - Have a QB+WR1 stack (clean primary)
  //   - Avoid drafting your top two WRs same-team-as-QB (over-concentration)
  //   - Keep ≤7 players sharing any single bye week
  //   - Avoid 2+ RBs from one NFL team (backfield cannibalization)
  //   - Avoid 2+ WRs from one team without that team's QB (un-anchored corr)
  //   - At least 1 distinct QB stack on the roster (naked QB underperforms)
  // Projections tab — your live roster's projected PPG by position vs one of
  // three baselines (portfolio / total / draft room). Uses p.pPg from
  // data/players.json. Baselines:
  //   - portfolio: avg of your past drafted teams (chrome.storage mff_portfolio)
  //   - room: avg of the other 11 teams in THIS live draft (reconstructed
  //           from state.history via slotFromPick)
  //   - total: pooled avg = portfolio teams + this draft's opponents
  // No-ops gracefully when data isn't ready (no roster yet, no portfolio).
  function renderProjections() {
    const wrap = document.getElementById('mff-projections-wrap');
    if (!wrap || wrap.style.display === 'none') return;
    const blEl = document.getElementById('mff-proj-baseline');
    const infoEl = document.getElementById('mff-proj-info');
    const gridEl = document.getElementById('mff-proj-grid');
    const totalEl = document.getElementById('mff-proj-total');
    const rosterEl = document.getElementById('mff-proj-roster');
    if (!blEl || !infoEl || !gridEl || !totalEl || !rosterEl) return;

    const POS = ['QB','RB','WR','TE'];
    const POS_COLORS = { QB: '#ef4444', RB: '#22c55e', WR: '#3b82f6', TE: '#f59e0b' };

    // --- 1) Your live roster aggregation ---
    const mine = { QB: 0, RB: 0, WR: 0, TE: 0 };
    const mineCount = { QB: 0, RB: 0, WR: 0, TE: 0 };
    const byPos = { QB: [], RB: [], WR: [], TE: [] };
    state.myRoster.forEach(p => {
      if (mine[p.s] == null) return;
      mine[p.s] += (p.pPg || 0);
      mineCount[p.s]++;
      byPos[p.s].push(p);
    });
    const myTotal = mine.QB + mine.RB + mine.WR + mine.TE;

    function _teamPosSums(playerObjs) {
      const out = { QB: 0, RB: 0, WR: 0, TE: 0 };
      playerObjs.forEach(p => { if (p && out[p.s] != null) out[p.s] += (p.pPg || 0); });
      return out;
    }

    // --- 2) Portfolio baseline (your past teams from chrome.storage) ---
    let portfolioAvg = null;
    if (state.portfolio && Array.isArray(state.portfolio.teams) && state.portfolio.teams.length) {
      const sums = { QB: 0, RB: 0, WR: 0, TE: 0 };
      let n = 0;
      state.portfolio.teams.forEach(team => {
        if (!Array.isArray(team) || !team.length) return;
        const objs = team.map(name => state.byName.get(name)).filter(Boolean);
        const ts = _teamPosSums(objs);
        sums.QB += ts.QB; sums.RB += ts.RB; sums.WR += ts.WR; sums.TE += ts.TE;
        n++;
      });
      if (n > 0) {
        portfolioAvg = {
          QB: sums.QB / n, RB: sums.RB / n, WR: sums.WR / n, TE: sums.TE / n,
          teamCount: n
        };
      }
    }

    // --- 3) Draft room baseline (other 11 teams in this draft) ---
    let roomAvg = null;
    if (state.history && state.history.length > 0) {
      const slotRosters = {};
      state.history.forEach(h => {
        const sl = slotFromPick(h.prevPick);
        if (!slotRosters[sl]) slotRosters[sl] = [];
        const p = state.byName.get(h.name);
        if (p) slotRosters[sl].push(p);
      });
      const sums = { QB: 0, RB: 0, WR: 0, TE: 0 };
      let n = 0;
      for (let s = 1; s <= TEAM_SIZE; s++) {
        if (state.slot && s === state.slot) continue; // exclude yourself
        const roster = slotRosters[s] || [];
        if (!roster.length) continue;
        const ts = _teamPosSums(roster);
        sums.QB += ts.QB; sums.RB += ts.RB; sums.WR += ts.WR; sums.TE += ts.TE;
        n++;
      }
      if (n > 0) {
        roomAvg = {
          QB: sums.QB / n, RB: sums.RB / n, WR: sums.WR / n, TE: sums.TE / n,
          teamCount: n
        };
      }
    }

    // --- 4) Total baseline (pooled portfolio + room) ---
    let totalAvg = null;
    if (portfolioAvg && roomAvg) {
      const pc = portfolioAvg.teamCount, rc = roomAvg.teamCount;
      totalAvg = {
        QB: (portfolioAvg.QB * pc + roomAvg.QB * rc) / (pc + rc),
        RB: (portfolioAvg.RB * pc + roomAvg.RB * rc) / (pc + rc),
        WR: (portfolioAvg.WR * pc + roomAvg.WR * rc) / (pc + rc),
        TE: (portfolioAvg.TE * pc + roomAvg.TE * rc) / (pc + rc),
        teamCount: pc + rc
      };
    } else {
      totalAvg = portfolioAvg || roomAvg;
    }

    // Resolve active baseline; fall back to whichever is available.
    let active = state.projBaseline;
    const available = { portfolio: !!portfolioAvg, total: !!totalAvg, room: !!roomAvg };
    if (!available[active]) {
      active = available.portfolio ? 'portfolio' :
               available.total ? 'total' :
               available.room ? 'room' : 'portfolio';
      state.projBaseline = active;
    }
    const baseline = active === 'total' ? totalAvg :
                     active === 'room' ? roomAvg :
                     portfolioAvg;

    // --- 5) Render baseline toggle ---
    const BL_DEFS = [
      { id: 'portfolio', label: 'PORTFOLIO', tip: 'Avg across your past drafted teams' },
      { id: 'total',     label: 'TOTAL',     tip: 'Pooled: your portfolio + this draft room' },
      { id: 'room',      label: 'ROOM',      tip: 'Avg of the other 11 teams in this draft' }
    ];
    let blHtml = '';
    BL_DEFS.forEach(b => {
      const isActive = active === b.id;
      const disabled = !available[b.id];
      blHtml += `<button class="mff-proj-bl${isActive ? ' active' : ''}${disabled ? ' disabled' : ''}" data-bl="${b.id}" title="${b.tip}"${disabled ? ' disabled' : ''}>${b.label}</button>`;
    });
    blEl.innerHTML = blHtml;
    blEl.querySelectorAll('.mff-proj-bl').forEach(btn => {
      btn.addEventListener('click', () => {
        if (btn.disabled) return;
        const id = btn.dataset.bl;
        if (!id || !available[id]) return;
        state.projBaseline = id;
        renderProjections();
      });
    });

    // --- 6) Baseline info line ---
    if (baseline) {
      const blLabel = active === 'total' ? 'Total Avg' :
                      active === 'room' ? 'Room Avg' :
                      'Portfolio Avg';
      const teamWord = baseline.teamCount === 1 ? 'team' : 'teams';
      infoEl.textContent = `vs. ${blLabel} (${baseline.teamCount} ${teamWord})`;
    } else {
      infoEl.textContent = 'No baseline yet — keep drafting or sync your portfolio.';
    }

    // --- 7) Position grid ---
    let gridHtml = '';
    POS.forEach(pos => {
      const yourVal = mine[pos];
      const blVal = baseline ? baseline[pos] : null;
      const delta = blVal != null ? yourVal - blVal : null;
      const deltaColor = delta == null ? '#8a8d96' :
                         delta >= 1.5 ? '#22c55e' :
                         delta >= 0.3 ? '#4ade80' :
                         delta >= -0.3 ? '#cbd5e1' :
                         delta >= -1.5 ? '#facc15' :
                         delta >= -3 ? '#f59e0b' :
                         '#ef4444';
      const deltaStr = delta == null ? '—' : (delta > 0 ? '+' : '') + delta.toFixed(1);
      gridHtml += `<div class="mff-proj-cell" style="border-top-color:${POS_COLORS[pos]}">`;
      gridHtml += `<div class="mff-proj-pos" style="color:${POS_COLORS[pos]}">${pos}</div>`;
      gridHtml += `<div class="mff-proj-val">${yourVal.toFixed(1)}</div>`;
      gridHtml += `<div class="mff-proj-sub">${mineCount[pos]} pick${mineCount[pos] === 1 ? '' : 's'}</div>`;
      gridHtml += `<div class="mff-proj-delta" style="color:${deltaColor}">${deltaStr}</div>`;
      gridHtml += `<div class="mff-proj-blval">${blVal != null ? 'avg ' + blVal.toFixed(1) : ''}</div>`;
      gridHtml += `</div>`;
    });
    gridEl.innerHTML = gridHtml;

    // --- 8) Total row ---
    if (baseline) {
      const blTotal = baseline.QB + baseline.RB + baseline.WR + baseline.TE;
      const tDelta = myTotal - blTotal;
      const tColor = tDelta >= 3 ? '#22c55e' :
                     tDelta >= 0.5 ? '#4ade80' :
                     tDelta >= -0.5 ? '#cbd5e1' :
                     tDelta >= -3 ? '#facc15' :
                     '#ef4444';
      totalEl.style.display = '';
      totalEl.innerHTML =
        `<span class="lbl">TEAM TOTAL</span>` +
        `<span class="v">${myTotal.toFixed(1)} PPG</span>` +
        `<span class="d" style="color:${tColor}">${tDelta > 0 ? '+' : ''}${tDelta.toFixed(1)}</span>`;
    } else {
      totalEl.style.display = 'none';
    }

    // --- 9) Per-player roster breakdown by position ---
    let rosterHtml = '<div class="mff-proj-roster-head">YOUR ROSTER · PROJ PPG</div>';
    if (state.myRoster.length === 0) {
      rosterHtml += '<div class="mff-proj-empty">No picks yet — recommendations refresh once you start drafting.</div>';
    } else {
      POS.forEach(pos => {
        const players = byPos[pos];
        if (!players.length) return;
        players.sort((a, b) => (b.pPg || 0) - (a.pPg || 0));
        rosterHtml += `<div class="mff-proj-roster-group">`;
        rosterHtml += `<div class="mff-proj-roster-grouphead" style="color:${POS_COLORS[pos]}">${pos} <span class="ct">${mine[pos].toFixed(1)} PPG · ${players.length}</span></div>`;
        players.forEach(p => {
          rosterHtml += `<div class="mff-proj-roster-player"><span class="n">${p.n}</span><span class="t">${teamAbbr(p.t)}</span><span class="v">${(p.pPg || 0).toFixed(1)}</span></div>`;
        });
        rosterHtml += `</div>`;
      });
    }
    rosterEl.innerHTML = rosterHtml;
  }

  // Live "next pick advance rate" panel — for the user's current pick
  // number, computes what the advance rate would be for taking the
  // NEXT QB / RB / WR / TE pick at that round, at all 3 BBM levels:
  //   QF  = made quarterfinals (top-2 / 12)         baseline ~16.67%
  //   SF  = made semifinals                          baseline ~1.32%
  //   Fin = made finals                              baseline ~0.082%
  // Uses BBM_PICK_BY_RANK_ROUND from data/bbm_pick_by_rank_round.js.
  // Highlights the highest QF-lift position with a green tint per row.
  // v0.10.56: VALUE BOARD — per-position chart of the REC sort's heavy
  // buff/nerf multipliers.
  // v0.10.57: standard best ball now uses REAL Underdog BBM history
  // (BBM II–VI, 2.6M teams): bar + number = historical advance-rate lift
  // of taking your NEXT player at that position in the current round
  // (50/30/20 QF/SF/Finals blend). SF/Redraft fall back to the VOR model
  // (BBM tables are STD-best-ball only).
  function renderValueChart() {
    const el = document.getElementById("mff-value-chart");
    if (!el) return;
    if (!ENGINE.recValueChartData || !state.players || !state.players.length) { el.innerHTML = ""; return; }
    let chart, source;
    const mode = state.isRedraft ? "rd" : "bb";
    const round = Math.max(1, Math.min(18, Math.ceil((state.pickNum || 1) / (TEAM_SIZE || 12))));
    try {
      const avail = state.players.filter(p => !state.drafted.has(p.n) && !p.ir);
      const data = ENGINE.recValueChartData(avail, state.myRoster || [], state.isSuperflex, mode, round);
      chart = data.positions;
      source = data.source;
    } catch (e) { el.innerHTML = ""; return; }
    const posColors = { QB: "#ef4444", RB: "#22c55e", WR: "#3b82f6", TE: "#f59e0b" };
    const isBbm = source === "bbm";
    let maxVal = isBbm ? 0.01 : 1;
    for (const pos of ["QB", "RB", "WR", "TE"]) {
      const c = chart[pos];
      const v = c ? (isBbm ? c.lift : c.avail) : null;
      if (v != null && v > maxVal) maxVal = v;
    }
    const modeLabel = state.isRedraft ? "REDRAFT · VOR" : state.isSuperflex ? "SUPERFLEX · VOR" : "BBM II–VI @ R" + round;
    let rows = "";
    for (const pos of ["QB", "RB", "WR", "TE"]) {
      const c = chart[pos];
      if (!c) continue;
      const m = c.mult;
      const mCol = m >= 1.08 ? "#22c55e" : m >= 0.95 ? "#94a3b8" : m >= 0.80 ? "#f59e0b" : "#ef4444";
      const mStr = "×" + m.toFixed(2);
      let barPct, valStr, fillTxt, rowTitle;
      if (isBbm) {
        barPct = (c.lift != null && c.lift > 0) ? Math.max(4, Math.round(c.lift / maxVal * 100)) : 4;
        valStr = c.lift != null ? c.lift.toFixed(2) + "x" : "—";
        fillTxt = '<span style="color:#64748b">#' + c.nextRank + "</span>";
        rowTitle = pos + ": teams that took " + pos + c.nextRank + " in R" + round +
          " historically advanced at " + valStr + " baseline (BBM II–VI" +
          (c.n != null ? ", n=" + c.n.toLocaleString() : "") + ", 50/30/20 QF/SF/Finals blend)" +
          (c.rel != null ? " • " + (c.rel >= 0 ? "+" : "") + c.rel + " vs cross-position avg" : "") +
          " • REC multiplier " + mStr;
      } else {
        barPct = (c.avail != null && c.avail > 0) ? Math.max(4, Math.round(c.avail / maxVal * 100)) : 4;
        valStr = c.avail != null ? ((c.avail >= 0 ? "+" : "") + c.avail) : "—";
        const isFull = c.fillPct >= 100;
        fillTxt = isFull
          ? '<span style="color:#ef4444;font-weight:700">FULL</span>'
          : '<span style="color:' + (c.fillPct >= 75 ? "#f59e0b" : "#64748b") + '">' + c.have + "/" + c.target + "</span>";
        rowTitle = pos + ": top-3 available avg VOR " + valStr +
          (c.rel != null ? " (" + (c.rel >= 0 ? "+" : "") + c.rel + " vs cross-position avg)" : "") +
          " • roster fill " + c.have + "/" + c.target +
          " • REC multiplier " + mStr + " (avail " + c.relMult.toFixed(2) + " × fill " + c.fillMult.toFixed(2) + ")";
      }
      rows += '<div style="display:flex;align-items:center;gap:6px;line-height:1.5" title="' + rowTitle.replace(/"/g, "&quot;") + '">' +
        '<span style="flex:0 0 20px;color:' + posColors[pos] + ';font-weight:700">' + pos + '</span>' +
        '<span style="flex:1;min-width:0;background:#1e2027;border-radius:3px;height:7px;overflow:hidden">' +
          '<span style="display:block;height:100%;width:' + barPct + '%;background:' + posColors[pos] + ';opacity:' + (m < 0.80 ? "0.35" : m < 0.95 ? "0.6" : "0.9") + '"></span>' +
        '</span>' +
        '<span style="flex:0 0 34px;text-align:right;color:#cbd5e1;font-family:monospace">' + valStr + '</span>' +
        '<span style="flex:0 0 32px;text-align:right;font-family:monospace">' + fillTxt + '</span>' +
        '<span style="flex:0 0 40px;text-align:right;color:' + mCol + ';font-weight:700;font-family:monospace">' + mStr + '</span>' +
        '</div>';
    }
    const headTitle = isBbm
      ? "Real BBM II–VI history: advance-rate lift of taking your next player at each position this round, your next positional rank (#N), and the resulting REC-sort buff/nerf"
      : "Value still available per position (bar + number = avg VOR of the top-3 on the board), your roster fill, and the resulting REC-sort buff/nerf";
    el.innerHTML =
      '<div style="font-size:9px;letter-spacing:.8px;color:#8a8d96;text-transform:uppercase;font-weight:600;margin-bottom:3px;display:flex;justify-content:space-between">' +
        '<span title="' + headTitle.replace(/"/g, "&quot;") + '">VALUE BOARD</span>' +
        '<span style="color:#64748b">' + modeLabel + '</span>' +
      '</div>' +
      '<div style="display:flex;flex-direction:column;gap:2px;font-size:.62rem">' + rows + '</div>';
  }

  function renderNextPickRates() {
    const el = document.getElementById('mff-next-pick-rates');
    if (!el) return;
    if (typeof BBM_PICK_BY_RANK_ROUND === 'undefined' || typeof BBM_BASELINE_QF_RATE === 'undefined') {
      el.innerHTML = ''; return;
    }
    // BBM data is STD-best-ball only — hide for SF and Redraft.
    if (state.isSuperflex || state.isRedraft) { el.innerHTML = ''; return; }
    if (state.slot == null || !state.pickNum) { el.innerHTML = ''; return; }
    const round = Math.ceil(state.pickNum / 12);
    if (round < 1 || round > 18) { el.innerHTML = ''; return; }
    // Current per-position counts on user's roster
    const roster = state.myRoster || [];
    const counts = { QB:0, RB:0, WR:0, TE:0 };
    roster.forEach(p => { if (counts[p.s] != null) counts[p.s]++; });
    const POS_LIST = ['QB','RB','WR','TE'];
    const POS_COLORS = { QB:'#ef4444', RB:'#22c55e', WR:'#3b82f6', TE:'#f59e0b' };
    const STAGES = [
      { key: 'qf',  label: '→QF',  base: BBM_BASELINE_QF_RATE,  decimals: 1 },
      { key: 'sf',  label: '→SF',  base: BBM_BASELINE_SF_RATE,  decimals: 2 },
      { key: 'fin', label: '→Fin', base: BBM_BASELINE_FIN_RATE, decimals: 3 },
    ];
    const rows = [];
    // Track the "best" position per stage by lift
    const bestPerStage = { qf: null, sf: null, fin: null };
    const bestLiftPerStage = { qf: -Infinity, sf: -Infinity, fin: -Infinity };
    for (const pos of POS_LIST) {
      const nextRank = counts[pos] + 1;
      const tbl = BBM_PICK_BY_RANK_ROUND[pos.toLowerCase()];
      const cell = (tbl && tbl[nextRank] && tbl[nextRank][round]) || null;
      const stages = {};
      for (const s of STAGES) {
        const rate = cell ? cell[s.key] : null;
        const lift = rate != null ? rate / s.base : null;
        stages[s.key] = { rate, lift };
        if (lift != null && lift > bestLiftPerStage[s.key]) {
          bestLiftPerStage[s.key] = lift;
          bestPerStage[s.key] = pos;
        }
      }
      rows.push({ pos, nextRank, n: cell ? cell.n : null, stages });
    }
    function liftColor(lift) {
      if (lift == null) return '#64748b';
      if (lift >= 1.10) return '#22c55e';
      if (lift >= 1.00) return '#86efac';
      if (lift >= 0.90) return '#cbd5e1';
      return '#ef4444';
    }
    let html = '<div style="font-size:9px;letter-spacing:.8px;color:#8a8d96;text-transform:uppercase;font-weight:600;margin-bottom:4px">' +
               'NEXT PICK ADVANCE RATE — R' + round + ' (Pick ' + state.pickNum + ')' +
               '</div>';
    html += '<table style="width:100%;border-collapse:collapse;font-size:.62rem">';
    html += '<thead><tr style="color:#64748b;font-size:.55rem">' +
            '<th style="text-align:left;padding:1px 3px">PICK</th>' +
            STAGES.map(s => '<th style="text-align:right;padding:1px 3px">' + s.label + '</th>').join('') +
            '</tr></thead><tbody>';
    for (const r of rows) {
      html += '<tr>';
      html += '<td style="padding:2px 3px;color:' + POS_COLORS[r.pos] + ';font-weight:700">' + r.pos + r.nextRank + '</td>';
      for (const s of STAGES) {
        const cell = r.stages[s.key];
        const isBest = r.pos === bestPerStage[s.key] && cell.lift != null;
        const col = liftColor(cell.lift);
        const bg = isBest ? 'background:rgba(34,197,94,.16);' : '';
        const rateStr = cell.rate != null
          ? (cell.rate * 100).toFixed(s.decimals) + '%'
          : '—';
        const liftStr = cell.lift != null ? cell.lift.toFixed(2) + 'x' : '';
        html += '<td style="padding:2px 3px;text-align:right;' + bg + '" ' +
                'title="' + (cell.rate != null ? rateStr + ' (' + liftStr + ')' : 'no data') + '">' +
                '<span style="color:' + col + ';font-weight:600">' + rateStr + '</span>' +
                '<div style="font-size:.5rem;color:' + col + ';opacity:.75">' + liftStr + '</div>' +
                '</td>';
      }
      html += '</tr>';
    }
    html += '</tbody></table>';
    // Footer: name the OPTIMAL position for QF (the round that's right now)
    if (bestPerStage.qf) {
      html += '<div style="margin-top:3px;font-size:.58rem;color:#22c55e;text-align:right">' +
              '★ ' + bestPerStage.qf + ' best QF lift' +
              (bestPerStage.fin && bestPerStage.fin !== bestPerStage.qf
                ? ' / ' + bestPerStage.fin + ' best Fin lift' : '') +
              '</div>';
    }
    el.innerHTML = html;
  }

  function renderConstructionChecklist() {
    const el = document.getElementById('mff-construction-check');
    if (!el) return;
    const roster = state.myRoster || [];
    if (!roster.length) { el.innerHTML = ''; return; }
    // BBM-derived rules (must-take counts, path-aware cliffs, etc.) are
    // grounded in STANDARD-format BBM data only. Hide for Superflex —
    // the structural patterns there (e.g. 2-QB starter requirement) make
    // these rules incorrect. Hidden for Redraft too (best-ball rules).
    if (state.isSuperflex || state.isRedraft) { el.innerHTML = ''; return; }

    // Identify QB1 + per-team counts.
    const qbs = roster.filter(p => (p.s === 'QB') && p.t);
    const qb1 = qbs[0];
    const qb1Team = qb1 ? qb1.t : null;
    const qbTeams = new Set(qbs.map(q => q.t).filter(Boolean));

    // WR1 / WR2 same-team-as-QB1.
    const wrs = roster.filter(p => p.s === 'WR');
    const wr1 = wrs[0];
    const wr2 = wrs[1];
    const hasWr1Stack = qb1Team && wr1 && wr1.t === qb1Team;
    const hasWr2Stack = qb1Team && wr2 && wr2.t === qb1Team;
    const wr1AndWr2 = hasWr1Stack && hasWr2Stack;

    // Bye concentration.
    const byeCount = {};
    roster.forEach(p => {
      const w = p.bye;
      if (w != null && w > 0) byeCount[w] = (byeCount[w] || 0) + 1;
    });
    const maxBye = Object.values(byeCount).reduce((m, c) => Math.max(m, c), 0);

    // RB cannibalization.
    const rbCount = {};
    roster.forEach(p => {
      if (p.s === 'RB' && p.t) rbCount[p.t] = (rbCount[p.t] || 0) + 1;
    });
    const maxRbSameTeam = Object.values(rbCount).reduce((m, c) => Math.max(m, c), 0);

    // WR cannibalization without QB anchor.
    const wrNoQbCount = {};
    roster.forEach(p => {
      if (p.s === 'WR' && p.t && !qbTeams.has(p.t)) {
        wrNoQbCount[p.t] = (wrNoQbCount[p.t] || 0) + 1;
      }
    });
    const maxWrNoQb = Object.values(wrNoQbCount).reduce((m, c) => Math.max(m, c), 0);

    // Distinct QB stacks (count of QBs with ≥1 same-team pass-catcher).
    const stackByQb = {};
    qbs.forEach(q => { stackByQb[q.t] = 0; });
    roster.forEach(p => {
      if ((p.s === 'WR' || p.s === 'TE' || p.s === 'RB') && p.t && stackByQb[p.t] != null) {
        stackByQb[p.t]++;
      }
    });
    const nQbStacks = Object.values(stackByQb).filter(n => n >= 1).length;

    // Build the checklist items. Status: 'good' / 'warn' / 'bad' / 'pending'.
    const items = [];
    if (qbs.length === 0) {
      items.push({ status: 'pending', text: 'Draft a QB to start tracking stacks' });
    } else {
      items.push({
        status: hasWr1Stack ? 'good' : 'warn',
        text: hasWr1Stack ? 'QB+WR1 stacked (clean primary)' : 'No same-team WR1 with QB1',
      });
      items.push({
        status: wr1AndWr2 ? 'bad' : 'good',
        text: wr1AndWr2
          ? 'WR1 AND WR2 same team as QB — over-concentrated, ~5pp drag'
          : 'No double-WR same-team trap',
      });
      items.push({
        status: nQbStacks >= 1 ? (nQbStacks >= 3 ? 'good' : 'good') : 'warn',
        text: 'Distinct QB stacks: ' + nQbStacks +
              (nQbStacks >= 3 ? ' (peak)' : nQbStacks === 0 ? ' (naked, ~1pp drag)' : ''),
      });
    }
    items.push({
      status: maxRbSameTeam <= 1 ? 'good' : maxRbSameTeam === 2 ? 'warn' : 'bad',
      text: maxRbSameTeam <= 1
        ? 'No backfield cannibalization'
        : maxRbSameTeam + ' RBs from one team' +
          (maxRbSameTeam === 2 ? ' (~1pp drag)' : ' (~4pp drag)'),
    });
    items.push({
      status: maxWrNoQb <= 1 ? 'good' : maxWrNoQb === 2 ? 'warn' : 'bad',
      text: maxWrNoQb <= 1
        ? 'No un-anchored WR pairs'
        : maxWrNoQb + ' WRs same team without their QB' +
          (maxWrNoQb === 2 ? ' (~1pp drag)' : ' (~3-6pp drag)'),
    });
    if (maxBye > 0) {
      items.push({
        status: maxBye <= 7 ? 'good' : maxBye <= 9 ? 'warn' : 'bad',
        text: maxBye <= 7
          ? 'Bye spread OK (' + maxBye + ' max)'
          : maxBye + ' on shared bye' + (maxBye <= 9 ? ' (~1-2pp drag)' : ' (3-5pp drag)'),
      });
    }

    // Must-take roster-shape rules from per-pick advance rate analysis (2.6M
    // teams across 5 BBMs). Each "skip" rate vs the 16.67% baseline:
    //   2 QB: skip = 0.70   |  4 RB: skip = 0.71
    //   5 WR: skip = 0.55   |  6 WR: skip = 0.77   |  7 WR: skip = 0.93
    //   2 TE: skip = 0.73
    //   6+ RB: skipping is BETTER (1.04) -> light warn at 6 RBs
    const rbCountTotal = roster.filter(p => p.s === 'RB').length;
    const wrCountTotal = roster.filter(p => p.s === 'WR').length;
    const teCountTotal = roster.filter(p => p.s === 'TE').length;
    const qbCountTotal = qbs.length;
    if (qbCountTotal < 2) {
      items.push({ status: 'bad', text: 'Only ' + qbCountTotal + ' QB — need a 2nd (skip = -30% advance)' });
    }
    if (rbCountTotal < 4) {
      items.push({ status: 'bad', text: rbCountTotal + ' RBs — need 4+ (skipping RB4 = -29%)' });
    } else if (rbCountTotal >= 6) {
      items.push({ status: 'warn', text: rbCountTotal + ' RBs — 6+ slightly hurts (-3% vs 5)' });
    }
    if (wrCountTotal < 5) {
      items.push({ status: 'bad', text: wrCountTotal + ' WRs — need 5+ (skipping WR5 = -45%, biggest penalty in data)' });
    } else if (wrCountTotal < 6) {
      items.push({ status: 'warn', text: wrCountTotal + ' WRs — 6 is better (skipping WR6 = -23%)' });
    } else if (wrCountTotal < 7) {
      items.push({ status: 'warn', text: wrCountTotal + ' WRs — 7 is optimal (skipping WR7 = -7%)' });
    }
    if (teCountTotal < 2) {
      items.push({ status: 'bad', text: 'Only ' + teCountTotal + ' TE — need 2+ (skip = -27%)' });
    }

    // Path-aware live advice from the conditional construction analysis
    // (2.6M teams, scripts/aggregate_bbm_conditional_construction.py).
    // Detects the user's CURRENT build path and warns about path-specific
    // pitfalls — the kind that no static count rule catches.
    // Round = ceil(prevPick/12) from state.history; fall back to 0 if unknown.
    const pickRoundByName = {};
    (state.history || []).forEach(h => {
      if (h.name && h.prevPick) {
        pickRoundByName[h.name] = Math.ceil(h.prevPick / 12);
      }
    });
    let rbR4 = 0, wrR6 = 0, qb1Round = null, te1Round = null;
    // Walk roster IN DRAFT ORDER (earliest pick first) so we capture QB1/TE1.
    const ordered = roster.slice().sort((a, b) =>
      (pickRoundByName[a.n] || 99) - (pickRoundByName[b.n] || 99)
    );
    ordered.forEach(p => {
      const r = pickRoundByName[p.n] || 0;
      if (p.s === 'RB' && r && r <= 4) rbR4++;
      if (p.s === 'WR' && r && r <= 6) wrR6++;
      if (p.s === 'QB' && qb1Round == null && r) qb1Round = r;
      if (p.s === 'TE' && te1Round == null && r) te1Round = r;
    });
    // RB-path: detect Zero/Hero/Balanced/Heavy/Robust and warn
    if (rbR4 >= 4) {
      // Robust RB: cliff at 5+ RBs
      if (rbCountTotal >= 5) {
        items.push({ status: 'bad',
          text: 'Robust RB path (4 RBs by r4) + ' + rbCountTotal + ' total — STOP, 5th RB = -25% advance' });
      } else {
        items.push({ status: 'warn',
          text: 'Robust RB path detected — target 4 RBs total, do NOT add a 5th' });
      }
    } else if (rbR4 === 0 && roster.length >= 5) {
      items.push({ status: 'warn',
        text: 'Zero RB path — historical max advance lift only 0.85, no count fully recovers' });
    } else if (rbR4 === 2) {
      items.push({ status: 'good',
        text: 'Balanced RB path (2 by r4) — best historical path, target 5 RBs total' });
    }
    // QB-timing warning: r4-6 is sub-baseline across every continuation
    if (qb1Round && qb1Round >= 4 && qb1Round <= 6) {
      items.push({ status: 'warn',
        text: 'QB1 in round ' + qb1Round + ' — mid-QB range is sub-baseline regardless of total QB count' });
    } else if (qb1Round && qb1Round >= 10 && qb1Round <= 12 && qbCountTotal >= 3) {
      items.push({ status: 'good',
        text: 'Late QB (r' + qb1Round + ') + 3 QB total — championship build, +69% Finals lift' });
    }
    // TE-timing warning: r1-4 is sub-baseline across every continuation
    if (te1Round && te1Round <= 4) {
      items.push({ status: 'warn',
        text: 'TE1 in r' + te1Round + ' — early TE is sub-baseline regardless of total TEs' });
    }

    const dot = (st) => {
      if (st === 'good') return '<span style="color:#22c55e;font-weight:700">✓</span>';
      if (st === 'warn') return '<span style="color:#f59e0b;font-weight:700">!</span>';
      if (st === 'bad')  return '<span style="color:#ef4444;font-weight:700">✕</span>';
      return '<span style="color:#94a3b8;font-weight:700">·</span>';
    };
    el.innerHTML =
      '<div style="font-size:9px;letter-spacing:.8px;color:#8a8d96;text-transform:uppercase;font-weight:600;margin-bottom:4px">CONSTRUCTION CHECK</div>' +
      '<div style="display:flex;flex-direction:column;gap:3px;font-size:.7rem;line-height:1.3">' +
      items.map(it =>
        '<div style="display:flex;gap:6px;align-items:flex-start"><span style="flex:0 0 12px;text-align:center">' +
        dot(it.status) + '</span><span style="color:#cbd5e1;flex:1;min-width:0">' +
        it.text + '</span></div>'
      ).join('') +
      '</div>';
  }

  // v0.9.78: Render BBM optimal-build badge + per-position next-pick advance
  // rates. Inserts/updates two rows beneath the target counts.
  function _renderBbmAdvance(state, counts, targets) {
    if (!window.BBM_DATA || !window.MFFEngine || !window.MFFEngine.bbmNextPickRates) return;
    // BBM dataset is from STANDARD-format tournaments only — don't show
    // STD-derived "optimal" recommendations in Superflex mode (they don't
    // apply). Clear any stale DOM left over from a prior STD-mode render.
    if (state.isSuperflex || state.isRedraft) {
      const stale1 = document.getElementById('mff-bbm-badge');
      const stale2 = document.getElementById('mff-bbm-next');
      if (stale1) stale1.remove();
      if (stale2) stale2.remove();
      return;
    }
    // v0.10.1: tear down the now-removed "First Pick At Position" panel
    // if it lingers from a prior version's DOM.
    const _staleOdds = document.getElementById('mff-bbm-round-odds');
    if (_staleOdds) _staleOdds.remove();

    const wrap = document.getElementById('mff-roster-wrap');
    if (!wrap) return;

    let badge = document.getElementById('mff-bbm-badge');
    if (!badge) {
      badge = document.createElement('div');
      badge.id = 'mff-bbm-badge';
      badge.style.cssText = 'margin-top:8px;padding:6px 8px;background:rgba(255,209,102,.06);border:1px solid rgba(255,209,102,.18);border-radius:6px;font-size:.66rem;color:#cbd5e1;text-align:center;line-height:1.5';
      const targetRow = document.getElementById('mff-target-row');
      if (targetRow && targetRow.parentNode) {
        targetRow.parentNode.insertBefore(badge, targetRow.nextSibling);
      } else {
        wrap.appendChild(badge);
      }
    }
    // v0.10.0: removed the "Take next at pick #N" row — same data is now
    // shown in the bottom odds panel + the new "Next Pick Advance Rate"
    // panel beside the construction checklist. Tear down stale DOM.
    const _staleNext = document.getElementById('mff-bbm-next');
    if (_staleNext) _staleNext.remove();

    const slot = state.slot;
    const drafted = state.myRoster ? state.myRoster.length : 0;
    const prefix = (state.myRoster || []).slice(0, 6).map(function(p){
      return (p.s || '').charAt(0).toUpperCase();
    }).filter(function(c){ return c==='Q'||c==='R'||c==='W'||c==='T'; }).join('');

    // v0.9.93: pass active tournament level so badge + rate match the tab.
    const _badgeLvl = (window._mffOddsLevel === 's' || window._mffOddsLevel === 'f') ? window._mffOddsLevel : 'q';
    const _badgeBaseKey = { q:'made_quarters', s:'made_semis', f:'made_finals' }[_badgeLvl];
    const _badgeLabel = { q:'playoffs', s:'semis', f:'finals' }[_badgeLvl];
    const _badgeDecimals = { q:1, s:2, f:3 }[_badgeLvl];
    const opt = window.MFFEngine.bbmOptimalBuild(counts, slot, drafted, { prefix: prefix, level: _badgeLvl });
    if (opt) {
      const ratePct = (opt.q_rate * 100).toFixed(_badgeDecimals);
      const nK = opt.n >= 1000 ? (opt.n/1000).toFixed(1) + 'k' : opt.n;
      const baseQ = (window.BBM_DATA.meta.level_baselines[_badgeBaseKey] || 0.1667);
      const lift = opt.q_rate / baseQ;
      const liftCol = lift > 1.05 ? '#22c55e' : (lift < 0.95 ? '#ef4444' : '#94a3b8');
      // Slot baseline — informational. Slot effects are mostly year-specific
      // player-availability noise, not a structural roster-shape edge.
      let slotLine = '';
      if (slot && opt.slot_baseline != null) {
        const sb = (opt.slot_baseline * 100).toFixed(1);
        const sbLift = opt.slot_baseline / baseQ;
        const sbCol = sbLift > 1.05 ? '#22c55e' : (sbLift < 0.95 ? '#ef4444' : '#94a3b8');
        const slotBuild = opt.slot_rate != null ? ' \u2022 this build at slot ' + slot + ': <strong>' + (opt.slot_rate*100).toFixed(1) + '%</strong>' : '';
        slotLine = '<div style="margin-top:3px;font-size:.6rem;color:#94a3b8">Slot ' + slot + ' baseline (all builds): <span style="color:' + sbCol + '">' + sb + '%</span>' + slotBuild + '</div>';
      }
      badge.innerHTML =
        '<span style="color:#94a3b8;text-transform:uppercase;letter-spacing:.5px;font-size:.6rem">BBM Optimal Shape</span><br>' +
        '<strong style="color:#ffd166;font-size:.85rem">' + opt.QB + '/' + opt.RB + '/' + opt.WR + '/' + opt.TE + '</strong>' +
        ' <span style="color:#cbd5e1">\u2014 ' + _badgeLabel + ' <strong>' + ratePct + '%</strong></span>' +
        ' <span style="color:' + liftCol + '">(' + lift.toFixed(2) + '\u00d7 baseline)</span>' +
        ' <span style="color:#94a3b8">n=' + nK + '</span>' + slotLine;
    } else {
      badge.innerHTML = '<span style="color:#94a3b8">BBM data: no reachable build</span>';
    }

    // v0.10.0: "Take next at pick" cells removed \u2014 odds panel + new
    // "Next Pick Advance Rate" panel cover the same ground without the
    // duplicated row.

    // v0.10.1: removed "First Pick At Position" odds panel \u2014 the
    // "Next Pick Advance Rate" panel beside the construction checklist
    // already covers the same data for the user's upcoming pick across
    // all 3 tournament levels (QF/SF/Fin), so the static first-pick grid
    // was redundant. The TOP-2/SEMIS/FINALS tab toggle lived here too;
    // the BBM Optimal Shape badge now locks to the QF/playoffs level
    // (its existing default when window._mffOddsLevel is undefined).

    // v0.9.83: STACK STATUS — your QB+pass-catcher stack vs historical advance rates
    // v0.10.1: anchored to badge (was oddsPanel, removed).
    let stackRow = document.getElementById('mff-bbm-stack');
    if (!stackRow) {
      stackRow = document.createElement('div');
      stackRow.id = 'mff-bbm-stack';
      stackRow.style.cssText = 'margin-top:8px;padding:6px 8px;background:rgba(34,197,94,.05);border:1px solid rgba(34,197,94,.18);border-radius:6px;font-size:.66rem;line-height:1.45';
      badge.parentNode.insertBefore(stackRow, badge.nextSibling);
    }
    if (window.MFFEngine.bbmStackStats && state.myRoster && state.myRoster.length) {
      const ss = window.MFFEngine.bbmStackStats(state.myRoster);
      if (ss) {
        const labels = { no_qb_yet: 'No QB drafted yet',
                         no_stack: 'No stack \u2014 weakest historical profile',
                         onesie: 'Onesie stack (QB+1)',
                         full2: 'Full stack (QB+2 pass catchers)',
                         full3plus: 'Mega stack (QB+3 pass catchers)' };
        const lbl = labels[ss.category] || ss.category;
        const liftStr = ss.cat_lift ? ' (' + ss.cat_lift.toFixed(2) + 'x baseline)' : '';
        const rateStr = ss.cat_rate ? (ss.cat_rate*100).toFixed(1) + '% advance' : '';
        const liftCol = ss.cat_lift && ss.cat_lift > 1.05 ? '#22c55e' : (ss.cat_lift && ss.cat_lift < 0.95 ? '#ef4444' : '#94a3b8');
        let stacksDetail = '';
        if (ss.stacks && ss.stacks.length) {
          const sd = ss.stacks.filter(function(s){ return s.size > 0; }).map(function(s){
            const team = (s.team||'').replace(/^.*\s/, '');
            return s.qb.split(' ')[1] + ' \u2192 ' + team + ' (+'+s.size+')';
          }).join(', ');
          if (sd) stacksDetail = '<div style="margin-top:3px;color:#94a3b8;font-size:.6rem">' + sd + '</div>';
        }
        stackRow.innerHTML =
          '<span style="color:#94a3b8;text-transform:uppercase;letter-spacing:.5px;font-size:.6rem">BBM STACK</span><br>' +
          '<strong style="color:#86efac">' + lbl + '</strong> ' +
          '<span style="color:#cbd5e1">' + rateStr + '</span> ' +
          '<span style="color:' + liftCol + '">' + liftStr + '</span>' +
          (ss.n_stacked_qbs > 1 ? ' <span style="color:#a3e635">\u2022 ' + ss.n_stacked_qbs + ' QBs stacked!</span>' : '') +
          stacksDetail;

        // Stack opportunity hint when state.players is available
        if (window.MFFEngine.bbmStackOpportunities && state.players && state.drafted) {
          const avail = state.players.filter(function(p){ return !state.drafted.has(p.n) && !p.ir; });
          const opps = window.MFFEngine.bbmStackOpportunities(state.myRoster, avail);
          if (opps && opps.length) {
            const top = opps[0];
            const hintLabel = top.type === 'extend' ? 'Extend stack with ' + top.suggest + ' (' + (top.team||'').replace(/^.*\s/,'') + ' ' + top.pos + ')'
                                                   : 'Open stack: ' + top.suggest + ' (you have ' + top.pcCount + ' ' + (top.team||'').replace(/^.*\s/,'') + ' pass catchers)';
            stackRow.innerHTML += '<div style="margin-top:4px;padding-top:4px;border-top:1px solid rgba(34,197,94,.18);font-size:.6rem;color:#fbbf24">\u2605 ' + hintLabel + '</div>';
          }
        }
      } else {
        stackRow.innerHTML = '<span style="color:#94a3b8">Stack data unavailable</span>';
      }
    } else {
      stackRow.innerHTML = '';
    }

    // v0.10.2: pull #mff-next-pick-rates up to sit between the stack panel
    // and the milestones list so users see next-pick advance rates above
    // the checklist. The element is statically declared near the bottom of
    // #mff-roster-wrap; insertBefore here is idempotent (no-op when already
    // in place, otherwise moves the live node).
    const nextPickEl = document.getElementById('mff-next-pick-rates');
    if (nextPickEl && stackRow.parentNode) {
      stackRow.parentNode.insertBefore(nextPickEl, stackRow.nextSibling);
    }
    const _mileAnchor = nextPickEl || stackRow;

    // v0.9.81: TRUE-CLIFF MILESTONES — only the genuine 45+ pt cliffs.
    // Shows "by pick X you should have Y of pos Z" status as a checklist.
    // v0.10.2: anchored to next-pick-rates panel (was stackRow) so order is:
    //   badge → stackRow → nextPickEl → mileRow
    let mileRow = document.getElementById('mff-bbm-milestones');
    if (!mileRow) {
      mileRow = document.createElement('div');
      mileRow.id = 'mff-bbm-milestones';
      mileRow.style.cssText = 'margin-top:8px;display:flex;flex-direction:column;gap:3px;font-size:.66rem';
    }
    _mileAnchor.parentNode.insertBefore(mileRow, _mileAnchor.nextSibling);
    if (window.MFFEngine.bbmMilestones && drafted < 18) {
      const ms = window.MFFEngine.bbmMilestones(counts, drafted);
      if (ms && ms.length) {
        let html = '<div style="color:#94a3b8;text-transform:uppercase;letter-spacing:.5px;font-size:.6rem;margin-bottom:2px">True-Cliff Milestones</div>';
        for (let i = 0; i < ms.length; i++) {
          const m = ms[i];
          let bg, border, icon, color;
          if (m.status === 'done') {
            bg = 'rgba(34,197,94,.10)'; border = 'rgba(34,197,94,.3)'; icon = '\u2713'; color = '#86efac';
          } else if (m.status === 'at-risk') {
            bg = 'rgba(239,68,68,.20)'; border = 'rgba(239,68,68,.5)'; icon = '\u0021'; color = '#fca5a5';
          } else if (m.status === 'missed') {
            bg = 'rgba(115,115,115,.15)'; border = 'rgba(115,115,115,.3)'; icon = '\u2717'; color = '#737373';
          } else { // on-track
            bg = 'rgba(99,102,241,.08)'; border = 'rgba(99,102,241,.25)'; icon = '\u00B7'; color = '#cbd5e1';
          }
          // Show count progress + cliff note compactly
          const counter = '<span style="font-family:monospace;color:#94a3b8;font-size:.6rem;margin-left:4px">[' + m.have + '/' + m.min + ']</span>';
          const picksTxt = m.status === 'on-track' ? ' \u2022 ' + m.picksLeft + ' pick' + (m.picksLeft===1?'':'s') + ' left'
                          : (m.status === 'at-risk' ? ' \u2022 NEXT PICK!'
                             : (m.status === 'missed' ? ' \u2022 cliff already hit (-' + m.cliffDrop + ' pts)' : ''));
          html += '<div style="padding:5px 8px;background:' + bg + ';border:1px solid ' + border + ';border-radius:5px;color:' + color + ';line-height:1.35">' +
                  '<span style="display:inline-block;width:13px;font-weight:700">' + icon + '</span>' +
                  '<span>' + m.label + '</span>' + counter +
                  '<div style="font-size:.58rem;color:#64748b;margin-top:1px;margin-left:17px">' + m.rationale + picksTxt + '</div>' +
                  '</div>';
        }
        mileRow.innerHTML = html;
      } else {
        mileRow.innerHTML = '';
      }
    }
  }

  function recommendedRoster(myRoster, isSuperflex, teamSize) {
    const TOTAL_ROUNDS = 18;
    const counts = { QB: 0, RB: 0, WR: 0, TE: 0 };
    for (const p of myRoster || []) counts[p.s] = (counts[p.s] || 0) + 1;
    const drafted = myRoster ? myRoster.length : 0;

    // v0.9.78: BBM-driven optimal build. Uses historical advance rate
    // from 2.5M Underdog BBM rosters (BBM II-VI). Slot-aware via state.slot.
    // v0.10.56: skipped in Redraft — BBM data is best-ball only.
    const _isRd = (typeof state !== 'undefined' && state.isRedraft);
    if (!isSuperflex && !_isRd && window.MFFEngine && window.MFFEngine.bbmOptimalBuild && window.BBM_DATA) {
      const slot = (typeof state !== 'undefined' && state.slot) ? state.slot : null;
      // Build prefix from pick order: positions of first 6 picks as Q/R/W/T
      const prefix = (myRoster || []).slice(0, 6).map(function(p){
        return (p.s || '').charAt(0).toUpperCase();
      }).filter(function(c){ return c==='Q'||c==='R'||c==='W'||c==='T'; }).join('');
      const opt = window.MFFEngine.bbmOptimalBuild(counts, slot, drafted, { prefix: prefix });
      if (opt) {
        window.__mffBbmRate = { rate: opt.q_rate, n: opt.n, build: opt.build, source: opt.source, prefix: opt.prefix };
        return { QB: opt.QB, RB: opt.RB, WR: opt.WR, TE: opt.TE };
      }
    }
    window.__mffBbmRate = null;

    // Format defaults — typical winning roster shape on Underdog.
    // v0.9.71: anchored TE at 1 (was 2) and rebalanced so the four
    // counts sum to 18 — the actual UD best-ball draft length. Older
    // defaults summed to 17 and rounding could drop them to 16, leaving
    // 1-2 rounds unaccounted for in the "remaining" widget.
    // v0.9.67 — SF lineup is 1QB / 2RB / 2WR / 1TE / 1FLEX / 1SF (vs
    // standard 1QB / 2RB / 3WR / 1TE / 1FLEX). One fewer required WR
    // means less WR depth needed, so SF target moves a WR slot to RB.
    const defaults = _isRd
      ? { QB: 2, RB: 6, WR: 8, TE: 2 }   // RD: starters + useful bench only
      : isSuperflex
        ? { QB: 3, RB: 7, WR: 7, TE: 1 }   // SF: 18 total — fewer WRs needed
        : { QB: 2, RB: 7, WR: 8, TE: 1 };  // STD: 18 total

    // Position floors — never go below these regardless of tendency.
    const floors = _isRd
      ? { QB: 1, RB: 3, WR: 4, TE: 1 }
      : isSuperflex
        ? { QB: 2, RB: 4, WR: 4, TE: 1 }   // SF: WR floor 4 (was 5)
        : { QB: 1, RB: 4, WR: 5, TE: 1 };

    // Pre-tendency stage: not enough picks to know the user's lean.
    if (drafted < 4) return defaults;

    // Blend defaults with observed positional ratio. 60/40 in favor of
    // defaults so a few early picks don't completely warp the recommendation.
    const defaultTotal = defaults.QB + defaults.RB + defaults.WR + defaults.TE;
    const blended = {};
    for (const pos of ["QB", "RB", "WR", "TE"]) {
      const defaultRatio = defaults[pos] / defaultTotal;
      const tendencyRatio = counts[pos] / drafted;
      const blendedRatio = 0.6 * defaultRatio + 0.4 * tendencyRatio;
      blended[pos] = Math.round(blendedRatio * defaultTotal);
    }

    // Apply floors and never recommend fewer than current.
    for (const pos of ["QB", "RB", "WR", "TE"]) {
      blended[pos] = Math.max(blended[pos], floors[pos], counts[pos]);
    }

    // Make sure totals don't blow up — if rounding pushed us over, trim
    // the most over-allocated position back toward its default.
    let total = blended.QB + blended.RB + blended.WR + blended.TE;
    while (total > defaultTotal + 1) {
      // Find the position most over its default that we can trim.
      let trimPos = null, trimDelta = 0;
      for (const pos of ["QB", "RB", "WR", "TE"]) {
        const delta = blended[pos] - defaults[pos];
        if (delta > trimDelta && blended[pos] > floors[pos] && blended[pos] > counts[pos]) {
          trimDelta = delta;
          trimPos = pos;
        }
      }
      if (!trimPos) break;
      blended[trimPos] -= 1;
      total -= 1;
    }

    // v0.9.71: TOP UP if rounding cost us picks vs the default total. The
    // blend math used to round each position independently, so a 2/6/7/2
    // default could come out 2/5/8/1 = 16 — two picks short of an 18-round
    // draft. We now refill back up to defaultTotal, never adding to TE
    // (sticking with format default of 1) and never going past +1 over a
    // position's default. Most padding lands at RB/WR which is what users
    // want when they're already drafting heavy at those spots.
    while (total < defaultTotal) {
      // Pick the position furthest UNDER its default (excluding TE — we
      // don't want to silently add a TE2 the user is intentionally skipping).
      let addPos = null, addDeficit = 0;
      for (const pos of ["RB", "WR", "QB"]) {
        // Don't push more than 1 over the default for this position.
        if (blended[pos] >= defaults[pos] + 1) continue;
        const deficit = defaults[pos] - blended[pos];
        if (deficit > addDeficit) {
          addDeficit = deficit;
          addPos = pos;
        }
      }
      if (!addPos) {
        // Every non-TE position is already at default+1; stop.
        break;
      }
      blended[addPos] += 1;
      total += 1;
    }

    return blended;
  }

  function isMyTurn(pickNum, slot) {
    if (!slot) return false;
    const round = Math.ceil(pickNum / TEAM_SIZE);
    const pickInRound = ((pickNum - 1) % TEAM_SIZE) + 1;
    const expected = round % 2 === 1 ? slot : (TEAM_SIZE - slot + 1);
    return pickInRound === expected;
  }

  // Reverse of isMyTurn — returns which slot (1..TEAM_SIZE) owns a given pick
  // under standard snake order. Used by renderProjections to reconstruct each
  // opponent's roster from state.history for the Draft Room baseline.
  function slotFromPick(pickNum) {
    const round = Math.ceil(pickNum / TEAM_SIZE);
    const pickInRound = ((pickNum - 1) % TEAM_SIZE) + 1;
    return round % 2 === 1 ? pickInRound : (TEAM_SIZE - pickInRound + 1);
  }

  function picksUntilMyNext(pickNum, slot) {
    if (!slot) return "—";
    if (isMyTurn(pickNum, slot)) return "NOW";
    let p = pickNum;
    while (p <= TOTAL_PICKS) { if (isMyTurn(p, slot)) return p - pickNum; p++; }
    return "—";
  }

  // Load portfolio from chrome.storage.local (synced from MFF site by mff-bridge.js)
  // Apply rank overrides from MFF site → state.players. Rebuilds byName.
  // Also pulls superflex ADP (sfa) from the payload and converts it into a
  // superflex rank stored on each player as p.sfRank. We rank by sorting
  // every player who has an sfa, then numbering 1..N. Players without sfa
  // get sfRank = null (they fall back to standard rank in the engine).
  // v0.18.1: set once the jacks-official Firestore pull has landed. After
  // that, a site-bridge push may still refresh sfa/mineSfRank/IR but is no
  // longer allowed to move p.rank — the bridge reads whatever board the site
  // tab has in memory, and a tab sitting on Consensus (or one that hasn't
  // finished loading Jack's cloud board) used to clobber the correct ranks.
  let _jacksLiveApplied = false;
  function applyRankings(rankings, irOut, fromLive) {
    if (!Array.isArray(rankings) || !rankings.length) return 0;
    // OUT FOR SEASON (IR) names from the site — flagged players keep their
    // board slot on the site but are hidden from season rankings, so hide
    // them from the rec list / value charts here too (p.ir). Explicitly
    // clears the flag when a name drops off the list (un-hide restores).
    const irSet = new Set(Array.isArray(irOut) ? irOut : []);
    const rankMap = new Map();
    const sfaMap = new Map();
    const mineSfMap = new Map();
    for (const r of rankings) {
      if (!r || !r.n) continue;
      if (r.myRank && (fromLive || !_jacksLiveApplied)) rankMap.set(r.n, r.myRank);
      if (r.sfa != null) sfaMap.set(r.n, r.sfa);
      if (r.mineSfRank != null) mineSfMap.set(r.n, r.mineSfRank);
    }
    let updated = 0;
    for (const p of state.players) {
      const wasIr = !!p.ir;
      p.ir = irSet.has(p.n);
      if (p.ir !== wasIr) updated++;
      const newRank = rankMap.get(p.n);
      if (newRank != null && p.rank !== newRank) {
        p.rank = newRank;
        updated++;
      }
      const sfa = sfaMap.get(p.n);
      if (sfa != null) p.sfa = sfa;
    }
    // v0.9.15: superflex rank comes from the user's personal mine.superflex
    // board when available (so a premium user sees their exact custom SF
    // order). Fall back to ascending sfa for players the user hasn't ranked.
    if (mineSfMap.size) {
      for (const p of state.players) {
        const ur = mineSfMap.get(p.n);
        if (ur != null) p.sfRank = ur;
        else if (p.sfa != null) p.sfRank = null; // mark for ADP-based fill below
      }
      // Fill remaining sfRanks for players with sfa but no user rank,
      // numbering them after the user's last ranked player.
      const used = new Set();
      for (const p of state.players) if (p.sfRank != null) used.add(p.sfRank);
      const fillStart = used.size ? Math.max(...used) + 1 : 1;
      const adpPool = state.players.filter(p => p.sfRank == null && p.sfa != null)
        .slice().sort((a, b) => a.sfa - b.sfa);
      adpPool.forEach((p, i) => { p.sfRank = fillStart + i; });
    } else {
      // No user rankings — Jack's official SF board first (jSf, baked at
      // export), then ADP ordering for anyone not on the board.
      const sfPool = state.players.filter(p => p.jSf != null || p.sfa != null).slice().sort((a, b) => {
        const av = a.jSf != null ? a.jSf : 100000 + a.sfa;
        const bv = b.jSf != null ? b.jSf : 100000 + b.sfa;
        return av - bv;
      });
      sfPool.forEach((p, i) => { p.sfRank = i + 1; });
    }
    // Players without sfa, jSf, AND no user rank: clear so engine falls back.
    for (const p of state.players) { if (p.sfa == null && p.jSf == null && !mineSfMap.has(p.n)) p.sfRank = null; }
    state.players.sort((a, b) => (a.rank || 9999) - (b.rank || 9999));
    state.byName = new Map(state.players.map(p => [p.n, p]));
    return updated;
  }

  // v0.15.1: live Jack's boards straight from Firestore at page load — the
  // same rankings/jacks-official doc the Sleeper/ESPN/Yahoo helpers read.
  // Until now Underdog only got fresh boards via the MFF-site bridge
  // (mff_rankings in chrome.storage), which required opening the site after
  // every save. This fetch makes a plain Underdog page refresh enough.
  // Ordering: runs after loadStoredPortfolio()'s storage read (network is
  // slower than storage), so the Firestore copy — always >= bridge freshness
  // — wins; a live bridge push mid-session still applies via onChanged.
  function refreshJackBoards() {
    // PREMIUM (v0.17.2): the bundle only carries the free top-36 slice of
    // Jack's boards — the live full-board pull is premium-only. A non-premium
    // session is lock-screened anyway, so skipping the fetch changes nothing
    // visible; it just stops the full board from landing in a free install.
    try {
      chrome.storage.local.get(['mff_user'], (gu) => {
        const u = gu && gu.mff_user;
        if (!(u && u.premium && u.syncedAt && (Date.now() - u.syncedAt) < 24 * 60 * 60 * 1000)) return;
        _refreshJackBoardsNow();
      });
    } catch (_) {}
  }
  function _refreshJackBoardsNow() {
    const send = (type) => new Promise((resolve) => {
      try {
        chrome.runtime.sendMessage({ type }, (res) => {
          if (chrome.runtime.lastError || !res || !res.ok || !res.data) return resolve(null);
          resolve(res.data);
        });
      } catch (_) { resolve(null); }
    });
    // v0.18.4: jacks-official is premium-only read since 2026-08-13, so the
    // tokenless fetch 403s — fall back to the public top-36 mirror
    // (jacks-public, written on the same site save) so a session without a
    // fresh site-bridge push still gets a live top of the board.
    send('mff-jacks-fetch').then((doc) => {
      if (doc) return _applyJacksDoc(doc, true);
      send('mff-jacks-public-fetch').then((pub) => { if (pub) _applyJacksDoc(pub, false); });
    });
  }
  function _applyJacksDoc(doc, full) {
    try {
      const payload = JSON.parse(doc.fields.data.stringValue);
      const jacks = payload.jacks || {};
      // OUT FOR SEASON flag: {name: seasonYear} on the same doc; only
      // hides during the current season (season year rolls over March 1,
      // mirroring IR_SEASON in the site's app.js).
      const d0 = new Date();
      const irSeason = d0.getMonth() >= 2 ? d0.getFullYear() : d0.getFullYear() - 1;
      let irMap = {};
      try { irMap = JSON.parse((doc.fields.ir && doc.fields.ir.stringValue) || '{}') || {}; } catch (_) {}
      const irOut = Object.keys(irMap).filter((n) => irMap[n] === irSeason);
      const irSet = new Set(irOut);
      const bbOrder = (jacks.redraft && jacks.redraft._order) || [];
      const sfOrder = (jacks.superflex && jacks.superflex._order) || [];
      if (!bbOrder.length) return;
      // Compact ranks over players we actually carry (players.json pool
      // already excludes K/DST/retired) and skip IR names — matches the
      // page-bridge's buildRankMapFromBoard numbering.
      const sfRankByName = new Map();
      let sr = 0;
      for (let si = 0; si < sfOrder.length; si++) {
        const n = sfOrder[si];
        if (!state.byName.has(n) || irSet.has(n)) continue;
        sfRankByName.set(n, ++sr);
        // Live-refresh Jack's RAW superflex rank too: jSf is what the SF
        // tier chips key off (sfRank can be the user's own board), and it
        // must stay in the same raw numbering as the _posTiers boundaries.
        state.byName.get(n).jSf = si + 1;
      }
      if (!full) {
        // Top-36 slice: renumber every carried player NOT on the live SF
        // slice from N+1 in existing jSf order, so a player who fell out of
        // the live top-36 can't share a jSf with his replacement.
        const liveSf = new Set(sfOrder);
        const restSf = state.players
          .filter((p) => !liveSf.has(p.n) && typeof p.jSf === 'number')
          .sort((a, b) => a.jSf - b.jSf);
        let jr = sfOrder.length;
        for (const p of restSf) { p.jSf = ++jr; }
      }
      const rows = [];
      let r = 0;
      for (const n of bbOrder) {
        const p = state.byName.get(n);
        if (!p || irSet.has(n)) continue;
        r++;
        // sfa deliberately null — keeps the baked/live-ADP value; the
        // boards only carry rank order.
        rows.push({ n: n, s: p.s, t: p.t, myRank: r, sfa: null,
                    mineSfRank: full && sfRankByName.has(n) ? sfRankByName.get(n) : null });
      }
      if (!rows.length) return;
      const liveCount = rows.length;
      if (!full) {
        // Extend the rows over everyone else in their existing rank order —
        // applyRankings only touches listed rows, and a stale baked rank
        // <= 36 must not survive next to a live one. mineSfRank stays null
        // on every partial row so applyRankings derives sfRank from the
        // jSf ordering rebuilt above.
        const inLive = new Set(rows.map((row) => row.n));
        const rest = state.players
          .filter((p) => !inLive.has(p.n) && !irSet.has(p.n) && typeof p.rank === 'number')
          .sort((a, b) => a.rank - b.rank);
        for (const p of rest) {
          r++;
          rows.push({ n: p.n, s: p.s, t: p.t, myRank: r, sfa: null, mineSfRank: null });
        }
      }
      applyRankings(rows, irOut, true);
      if (full) _jacksLiveApplied = true;
      // Jack's ALL-board tier boundaries, re-based onto the same COMPACT
      // numbering as the live ranks above (raw board positions include
      // names we don't carry + IR — baked boundaries would drift by the
      // skipped count, up to ~30 rows deep in the board).
      const compactTierList = (order, tiersRaw, skip) => {
        if (!Array.isArray(tiersRaw) || !tiersRaw.length || !order.length) return null;
        const carriedBefore = []; // carried count among order[0..i-1]
        let c = 0;
        for (let i = 0; i < order.length; i++) {
          carriedBefore[i] = c;
          const nm = order[i];
          if (state.byName.has(nm) && !skip.has(nm)) c++;
        }
        const out = [];
        for (const t of tiersRaw) {
          if (!t || !(t.afterRank >= 1) || !t.label) continue;
          const idx = Math.min(t.afterRank - 1, order.length - 1);
          out.push({ a: carriedBefore[idx] + 1, l: String(t.label), n: String(t.name || '') });
        }
        out.sort((x, y) => x.a - y.a);
        return out;
      };
      const bbT = compactTierList(bbOrder, ((jacks.redraft || {})._posTiers || {}).ALL, irSet);
      state.tiers = state.tiers || {};
      if (bbT) {
        // Partial docs cut tiers at 36 — keep any deeper boundaries a
        // full/bridge apply already installed.
        state.tiers.rank = full ? bbT
          : bbT.filter((t) => t.a <= liveCount)
              .concat((state.tiers.rank || []).filter((t) => t.a > liveCount))
              .sort((x, y) => x.a - y.a);
      }
      // SF tiers stay in RAW board positions — they pair with p.jSf
      // (updated raw above), not the compacted sfRank.
      const sfRaw = ((jacks.superflex || {})._posTiers || {}).ALL;
      if (Array.isArray(sfRaw) && sfRaw.length) {
        const freshSf = sfRaw
          .filter(t => t && t.afterRank >= 1 && t.label)
          .map(t => ({ a: t.afterRank, l: String(t.label), n: String(t.name || '') }));
        state.tiers.jSf = full ? freshSf.sort((x, y) => x.a - y.a)
          : freshSf.filter((t) => t.a <= sfOrder.length)
              .concat((state.tiers.jSf || []).filter((t) => t.a > sfOrder.length))
              .sort((x, y) => x.a - y.a);
      }
      const upd = doc.fields.updatedAt ? ' · saved ' + doc.fields.updatedAt.stringValue.slice(0, 10) : '';
      console.log('[MFF] live Jack boards from Firestore: ' + liveCount + ' ranked' +
        (full ? '' : ' (top-36 slice)') + upd);
      if (document.getElementById('mff-recs') && typeof render === 'function') render();
    } catch (e) { console.warn('[MFF] jacks board apply failed:', e); }
  }

  // v0.15.2: long-lived tabs never re-fetched boards — re-pull when the tab is
  // refocused after 5+ minutes hidden ("saved on the site, came back here").
  let _boardsFetchedAt = Date.now();
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState !== 'visible') return;
    if (Date.now() - _boardsFetchedAt < 5 * 60 * 1000) return;
    _boardsFetchedAt = Date.now();
    refreshJackBoards();
  });

  // ---------- v0.9.2: portfolio exposure badges in Underdog's player list ----------
  // Scan visible player rows, match each to our player pool, inject a colored
  // badge showing the user's portfolio exposure %. Color intensity scales
  // with % so concentration jumps out at a glance. Re-runs on a 2s interval
  // because Underdog virtualizes the list (rows added/removed on scroll).
  function colorForExposure(pct) {
    // v0.9.5: bright red→green gradient so exposure pops at a glance.
    // 0% means "you have ZERO of this guy — fix that or move on"; 15%+
    // means well-covered. The colors map intuitively: red=danger/low,
    // green=good/high coverage.
    if (pct <= 0)  return { bg: '#ef4444', fg: '#fff' };       // bright red
    if (pct < 3)   return { bg: '#f97316', fg: '#fff' };       // red-orange
    if (pct < 7)   return { bg: '#f59e0b', fg: '#0e0f12' };    // orange
    if (pct < 12)  return { bg: '#eab308', fg: '#0e0f12' };    // amber/yellow
    if (pct < 15)  return { bg: '#a3b85f', fg: '#0e0f12' };    // yellow-green
    if (pct < 25)  return { bg: '#84cc16', fg: '#0e0f12' };    // lime
    return             { bg: '#22c55e', fg: '#0e0f12' };       // bright green
  }

  // Find a text node inside `root` whose trimmed text equals `target`.
  // Used to locate the team-abbrev cell in a row so we can insert the badge
  // right after it (inline) rather than absolute-positioning over the row.
  function findExactTextNode(root, target) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let n;
    while ((n = walker.nextNode())) {
      if ((n.textContent || '').trim() === target) return n;
    }
    return null;
  }

  // Position-aware color scales for PPG. The same raw number means very
  // different things by position (a 9 PPG RB is mediocre, a 9 PPG TE is
  // elite). These thresholds are roughly the 80th / 60th / 40th / 20th
  // percentile cutoffs by position in a half-PPR best-ball context.
  function colorForPpg(pos, ppg) {
    const TIERS = {
      QB: [22, 18, 14, 10],   // elite / good / mid / low cutoffs
      RB: [16, 12, 8, 5],
      WR: [15, 11, 7, 4],
      TE: [12, 8, 5, 3]
    };
    const t = TIERS[pos] || TIERS.WR;
    if (ppg >= t[0]) return { bg: '#22c55e', fg: '#0e0f12' };  // bright green (elite)
    if (ppg >= t[1]) return { bg: '#84cc16', fg: '#0e0f12' };  // lime
    if (ppg >= t[2]) return { bg: '#eab308', fg: '#0e0f12' };  // yellow
    if (ppg >= t[3]) return { bg: '#f97316', fg: '#fff' };     // orange
    return                  { bg: '#ef4444', fg: '#fff' };     // red
  }

  // Age color scales — younger is better for upside, but the curve is
  // position-specific. RBs age fast, QBs age slowly, WR/TE in between.
  function colorForAge(pos, age) {
    let t;
    if (pos === 'QB')      t = [25, 30, 33, 36]; // ≤25 elite, ≤30 ok, ≤33 mid, ≤36 aging
    else if (pos === 'RB') t = [23, 25, 27, 29];
    else if (pos === 'TE') t = [24, 27, 29, 31];
    else                   t = [24, 26, 28, 30]; // WR default
    if (age <= t[0]) return { bg: '#22c55e', fg: '#0e0f12' };  // young/elite
    if (age <= t[1]) return { bg: '#84cc16', fg: '#0e0f12' };
    if (age <= t[2]) return { bg: '#eab308', fg: '#0e0f12' };
    if (age <= t[3]) return { bg: '#f97316', fg: '#fff' };
    return                  { bg: '#ef4444', fg: '#fff' };     // aging out
  }

  // Color used for the NEED badge — mirrors the engine's existing need-* CSS.
  // Each position gets its own color so a glance at the player list shows
  // which rows fill which holes in the user's roster.
  function colorForNeed(pos) {
    if (pos === 'QB') return { bg: '#7c3aed', fg: '#fff' };  // purple
    if (pos === 'RB') return { bg: '#22c55e', fg: '#0e0f12' }; // green
    if (pos === 'WR') return { bg: '#3b82f6', fg: '#fff' };  // blue
    if (pos === 'TE') return { bg: '#f59e0b', fg: '#0e0f12' }; // amber
    return { bg: '#6b6e76', fg: '#e9e9ec' };
  }

  function decoratePlayerList() {
    if (!state.players || !state.players.length) return;
    const sidebarEl = document.getElementById('mff-sidebar');
    const pct = (state.portfolio && state.portfolio.percent) || null;
    // Pre-compute roster context once per pass — used for stack & need checks
    // on every row.
    const ENGINE = window.MFFEngine;
    const counts = ENGINE ? ENGINE.rosterCounts(state.myRoster || []) : null;
    const round = ENGINE ? ENGINE.pickToRound(state.pickNum || 1, TEAM_SIZE) : null;
    const detectNeed = window.MFFEngine_detectNeed;
    const myRoster = state.myRoster || [];
    // Skip stack/need overlays entirely when there's no roster context yet.
    const showStackNeed = state.slot != null && (myRoster.length > 0 || (round != null && round >= 6));

    // Walk candidates in REVERSE document order so deeper (leaf) matches are
    // processed before their ancestors. Then the ancestor's "any decorated
    // descendant?" check catches the already-injected badge and skips,
    // preventing duplicate badges on nested matching elements.
    const candidates = Array.from(document.querySelectorAll('div, li'));
    candidates.reverse();
    let injected = 0;
    for (const el of candidates) {
      // Skip the helper itself — we don't want our own rec cards to get
      // exposure badges from this scanner; they get their own portfolio
      // values through render().
      if (sidebarEl && (el === sidebarEl || sidebarEl.contains(el))) continue;

      // Already badged AND text still matches the stamped player? Skip.
      // Underdog reuses DOM nodes during virtualization, so we re-validate
      // each pass and re-decorate when the row content changed.
      const stamped = el.dataset.mffExposureFor;
      if (stamped) {
        const txt = (el.innerText || '').trim();
        if (txt && txt.indexOf(stamped) === 0) continue;
        // Row was reused for a different player — strip every MFF badge
        // and any old outline so the new player gets fresh decoration.
        const oldBadges = el.querySelectorAll(':scope .mff-exposure[data-mff-direct="1"], :scope .mff-ppg[data-mff-direct="1"], :scope .mff-age[data-mff-direct="1"], :scope .mff-adp-mvt[data-mff-direct="1"], :scope .mff-playoff-sos[data-mff-direct="1"], :scope .mff-playoff-row[data-mff-direct="1"]');
        oldBadges.forEach(b => b.remove());
        if (el.dataset.mffOutline) {
          el.style.boxShadow = '';
          el.dataset.mffOutline = '';
        }
        el.dataset.mffExposureFor = '';
      }

      // If a descendant element already got a badge in this pass, this is a
      // parent container — skip so the badge only shows on the leaf row.
      if (el.querySelector('.mff-exposure[data-mff-direct="1"], .mff-ppg[data-mff-direct="1"], .mff-age[data-mff-direct="1"], .mff-adp-mvt[data-mff-direct="1"], .mff-playoff-sos[data-mff-direct="1"], .mff-playoff-row[data-mff-direct="1"]')) continue;

      const text = (el.innerText || '').trim();
      if (!text || text.length > 300) continue;

      // Two row formats we want to decorate:
      //   1. Player pool: "Name\nPOS_RANK TEAM ..." (e.g. "Bijan Robinson\nRB1 ATL ...")
      //   2. Roster panel: "Name\nTEAM\n..." (no POS chip on the row — POS is the
      //      group header above; the team abbr stands alone on its own line)
      let name = null;
      let team = null;
      let player = null;
      // Track which format matched. Roster rows get matchup pills only —
      // the %, PPG, age, mvt pills are draft-decision signals not useful
      // on already-drafted players.
      let isRosterFormat = false;

      // Try format 1 first (player pool)
      const allPos = text.match(/\n((?:QB|RB|WR|TE)\d*)\s+([A-Z]{2,3})\b/g);
      if (allPos && allPos.length === 1) {
        const m = text.match(/^(.+?)\n((?:QB|RB|WR|TE)\d*)\s+([A-Z]{2,3})\b/);
        if (m) {
          name = m[1].trim();
          team = m[3];
          player = state.byName.get(name) || findPlayerLoose(name);
          if (!player) {
            // Strip trailing numbers (Bye/ADP/Pick on same line as name).
            const cleaned = name.split(/\s+[-\d]/)[0].trim();
            if (cleaned && cleaned !== name) {
              const cand = state.byName.get(cleaned) || findPlayerLoose(cleaned);
              if (cand) { player = cand; name = cleaned; }
            }
          }
        }
      }

      // Format 2 fallback (roster panel): scan visual lines to find a player
      // name + that player's actual team abbr appearing on separate lines.
      // The roster row may interleave stats between the name and team
      // (e.g. "Name\n13\n54.3\nBAL\nBye"), so we line-scan rather than regex.
      if (!player) {
        isRosterFormat = true;
        const lines = text.split('\n').map(s => s.trim()).filter(Boolean);
        for (let i = 0; i < lines.length && !player; i++) {
          // Strip trailing digits from the line in case stats are appended.
          const candidate = lines[i].split(/\s+[-\d]/)[0].trim();
          if (!candidate || candidate.length < 3 || candidate.length > 40) continue;
          // Must contain a space (real names) and start with capital letter.
          if (!/^[A-Z][A-Za-z'.\-]*\s+[A-Za-z]/.test(candidate)) continue;
          const cand2 = state.byName.get(candidate) || findPlayerLoose(candidate);
          if (!cand2) continue;
          // Now look for the player's team abbr appearing on a later line.
          const playerTeamAbbr = teamAbbr(cand2.t || '');
          if (!playerTeamAbbr) continue;
          for (let j = i + 1; j < lines.length; j++) {
            // Either the line equals exactly the team abbr, or starts with it.
            if (lines[j] === playerTeamAbbr ||
                new RegExp('^' + playerTeamAbbr + '\\b').test(lines[j])) {
              player = cand2;
              name = candidate;
              team = playerTeamAbbr;
              break;
            }
          }
        }
      }

      if (!player || !name || !team) continue;

      // Compute the three signals. Exposure now defaults to 0 if the player
      // isn't in the portfolio (so every row gets a colored % badge — 0%
      // shows in red, telling you "you have zero shares of this guy").
      // v0.9.73: try udN as fallback so Jr/Sr/III variants match.
      const _expKey = _portfolioKey(player, pct);
      const rawExposure = (pct && _expKey != null) ? pct[_expKey] : null;
      const exposure = (pct && rawExposure != null) ? rawExposure : (pct ? 0 : null);
      const stack = showStackNeed ? detectStack(player, myRoster) : null;
      // v0.9.74: TEAM (skill-skill correlation) only when no STACK present.
      // Renamed `team` → `teamSig` to avoid colliding with the NFL team
      // abbrev `team = m[3]` already declared above in this scope.
      const teamSig = (showStackNeed && !stack) ? detectTeam(player, myRoster) : null;
      const needFlag = (showStackNeed && detectNeed && counts && round != null)
        ? detectNeed(player.s, counts, round, state.isSuperflex, TEAM_SIZE)
        : null;

      // v0.10.28: BRINGBACK detection — fires when adding this player would
      // create a playoff-week (W15/16/17) bringback in a HIGH-total game
      // (O/U ≥ 47). Per BBM II-VI research, +10% QF→SF advance lift and
      // +6% SF→Finals lift on high-total bringbacks vs baseline. Low/mid
      // bringbacks ignored — the conditional lift only fires above 47.
      //
      // v0.10.29: WEEK 16/17 detection — broader playoff-week pairing
      // indicator. Fires when adding the player creates ANY pairing with
      // a roster player in W16 or W17 (same team OR opposing team, any
      // game total). Doesn't require the high-total condition that
      // BRINGBACK does — surfaces all SF/Finals roster correlations so
      // you can see your playoff-week exposure at a glance.
      let bringback = null;
      let weekPlayoff = null;
      if (showStackNeed
          && typeof window.MFF_PLAYOFF_SOS === 'object'
          && myRoster.length
          && (player.s === 'QB' || player.s === 'RB' || player.s === 'WR' || player.s === 'TE')) {
        const playerTeamAbbr = teamAbbr(player.t || '');
        const _teamRec = playerTeamAbbr ? window.MFF_PLAYOFF_SOS[playerTeamAbbr] : null;
        const _posRec = _teamRec ? _teamRec[player.s] : null;
        if (_posRec) {
          // Map team abbr → list of roster players on that team (excluding self).
          const myByTeam = {};
          myRoster.forEach(rp => {
            if (rp === player) return;
            const t = teamAbbr(rp.t || '');
            if (!t) return;
            if (!myByTeam[t]) myByTeam[t] = [];
            myByTeam[t].push(rp);
          });
          // BRINGBACK pass — opposing team + W15-17 + O/U ≥ 47.
          const bbHits = [];
          [15, 16, 17].forEach(w => {
            const m = _posRec[w];
            if (!m || typeof m.gameTotal !== 'number') return;
            if (m.gameTotal < 47) return;
            const oppPlayers = myByTeam[m.opp];
            if (oppPlayers && oppPlayers.length) {
              bbHits.push({ wk: w, opp: m.opp, total: m.gameTotal, oppPlayers });
            }
          });
          if (bbHits.length) bringback = { hits: bbHits };

          // WEEK 16/17 pass — same-team OR opposing-team pairing in SF/Finals
          // weeks, gated to HIGH-total games (O/U ≥ 47). Per BBM research the
          // playoff-pairing edge only materializes when the game projects to
          // score; low/mid totals are noise at best, negative at worst.
          const wpHits = [];
          [16, 17].forEach(w => {
            const m = _posRec[w];
            if (!m) return;
            if (typeof m.gameTotal !== 'number' || m.gameTotal < 47) return;
            const sameTeamPlayers = myByTeam[playerTeamAbbr] || [];
            const oppPlayers = myByTeam[m.opp] || [];
            if (sameTeamPlayers.length || oppPlayers.length) {
              wpHits.push({
                wk: w, opp: m.opp, total: m.gameTotal,
                sameTeam: sameTeamPlayers, opposing: oppPlayers,
              });
            }
          });
          if (wpHits.length) weekPlayoff = { hits: wpHits };
        }
      }
      // Decorate when ANY signal has data — exposure / PPG / age / stack / team / need.
      const hasAnySignal = exposure != null || player.pPg != null || player.age != null || !!stack || !!teamSig || !!bringback || !!weekPlayoff;
      if (!hasAnySignal) continue;

      // Apply row-level outline for STACK / NEED (replaces the inline
      // STACK/NEED badges from v0.9.4). STACK takes precedence when both
      // fire — same-team-as-roster is a more actionable / rarer signal
      // than "I'm light at this position."
      //
      // v0.9.9: walk UP from the matched leaf to find the largest ancestor
      // that still contains only one player record. The leaf often only
      // wraps the left "Name + POS Team" cell, so outlining there only
      // covered the left third of the visible row. The widest single-row
      // ancestor is the full visible row including ADP / Proj / chevron.
      let outlineTarget = el;
      let walker = el.parentElement;
      let depth = 0;
      const MAX_WALK_DEPTH = 4; // safety: full row is usually 2–3 levels up
      while (walker && depth < MAX_WALK_DEPTH) {
        const txt = (walker.innerText || '').trim();
        if (!txt || txt.length > 600) break;
        const allPosWalker = txt.match(/\n((?:QB|RB|WR|TE)\d*)\s+([A-Z]{2,3})\b/g);
        if (!allPosWalker || allPosWalker.length !== 1) break;
        // Still a single-row container — keep walking up.
        outlineTarget = walker;
        walker = walker.parentElement;
        depth++;
      }

      // Helper that builds the small floating "STACK" / "NEED" label that
      // rides on the top edge of the outlined row so the user can read what
      // the colored outline means at a glance.
      const makeRowLabel = (text, bg, fg) => {
        const lbl = document.createElement('span');
        lbl.className = 'mff-row-label';
        lbl.dataset.mffDirect = '1';
        lbl.dataset.mffFor = player.n;
        lbl.textContent = text;
        lbl.style.cssText = [
          'position:absolute',
          // v0.10.35: pinned to the top-right corner of the row, just left
          // of the chevron. Sits above the projection value so the
          // STACK/BB/NEED hint is the first thing the user reads on the
          // right side of the row.
          'top:2px',
          'left:auto',
          'right:6px',
          'background:' + bg,
          'color:' + fg,
          'font-size:8px',
          'font-weight:800',
          'letter-spacing:0.7px',
          'padding:1px 5px',
          'border-radius:2px',
          'pointer-events:none',
          'z-index:10',
          'line-height:1.2',
          'box-shadow:0 0 0 1px rgba(0,0,0,0.5)',
          'white-space:nowrap'
        ].join(';');
        return lbl;
      };

      // v0.10.27: STACK / TEAM / NEED outlines + labels only on PLAYER-POOL
      // rows. They flag opportunity vs the user's draft; on already-drafted
      // roster rows they're either obvious (the player IS the stack source)
      // or irrelevant (you already have them).
      if (!isRosterFormat) {
        if (stack) {
          outlineTarget.style.boxShadow = 'inset 0 0 0 2px #22c55e';
          outlineTarget.style.borderRadius = outlineTarget.style.borderRadius || '4px';
          if (getComputedStyle(outlineTarget).position === 'static') {
            outlineTarget.style.position = 'relative';
          }
          outlineTarget.dataset.mffOutline = 'stack';
          // v0.10.37: STACK keeps the green outline + priority, but if the
          // same row would also fire BRINGBACK or WEEK 16/17, append a brief
          // note so the user doesn't miss the playoff-week pairing. The
          // outline color stays green (stack is the dominant signal) and the
          // suffix uses BB/W16/W17 abbreviations to stay inside the corner
          // badge's footprint.
          const stackTitle = stack.kind === 'qb-stack'
            ? 'STACK — pairs with: ' + stack.with.map(x => x.n).join(', ')
            : 'STACK — pairs with QB: ' + stack.with[0].n;
          let combinedTitle = stackTitle;
          let labelSuffix = '';
          if (bringback) {
            const bbWeeks = bringback.hits.map(h => 'W' + h.wk).join('+');
            labelSuffix += ' · BB ' + bbWeeks;
            const bbDetail = bringback.hits.map(h =>
              'W' + h.wk + ' vs ' + h.opp + ' (' + h.total.toFixed(1) + ' O/U) — paired with ' +
              h.oppPlayers.map(p => p.n).join(', ')
            ).join('; ');
            combinedTitle += '\n⚡ BRINGBACK ' + bbWeeks + ' — ' + bbDetail;
          } else if (weekPlayoff) {
            const wpWeeks = weekPlayoff.hits.map(h => 'W' + h.wk).join('+');
            labelSuffix += ' · ' + wpWeeks;
            const wpDetail = weekPlayoff.hits.map(h => {
              const same = h.sameTeam && h.sameTeam.length
                ? 'same team: ' + h.sameTeam.map(p => p.n).join(', ')
                : '';
              const opp = h.opposing && h.opposing.length
                ? 'vs ' + h.opp + ': ' + h.opposing.map(p => p.n).join(', ')
                : '';
              return 'W' + h.wk + ' — ' + [same, opp].filter(Boolean).join('; ');
            }).join(' | ');
            combinedTitle += '\nWEEK ' + wpWeeks + ' — playoff-week roster overlap: ' + wpDetail;
          }
          outlineTarget.title = combinedTitle;
          // Label text: "★ STACK <LastName>" so user immediately sees who.
          const withName = (stack.with && stack.with[0] && stack.with[0].n)
            ? stack.with[0].n.split(' ').pop().toUpperCase()
            : '';
          outlineTarget.appendChild(makeRowLabel(
            '★ STACK' + (withName ? ' ' + withName : '') + labelSuffix,
            '#22c55e', '#0e0f12'
          ));
        } else if (bringback) {
          // v0.10.28: Gold outline for high-total playoff-week bringbacks.
          // +10% QF→SF / +6% SF→Finals advance lift (BBM II-VI, n=2.6M teams).
          outlineTarget.style.boxShadow = 'inset 0 0 0 2px #f59e0b';
          outlineTarget.style.borderRadius = outlineTarget.style.borderRadius || '4px';
          if (getComputedStyle(outlineTarget).position === 'static') {
            outlineTarget.style.position = 'relative';
          }
          outlineTarget.dataset.mffOutline = 'bringback';
          const weeksStr = bringback.hits.map(h => 'W' + h.wk).join('+');
          const detail = bringback.hits.map(h =>
            'W' + h.wk + ' vs ' + h.opp + ' (' + h.total.toFixed(1) + ' O/U) — paired with ' +
            h.oppPlayers.map(p => p.n).join(', ')
          ).join('; ');
          outlineTarget.title = '⚡ BRINGBACK ' + weeksStr +
            ' — high-total (≥47) playoff game(s) with: ' + detail +
            '. +10% QF advance / +6% SF lift (BBM II-VI).';
          outlineTarget.appendChild(makeRowLabel('⚡ BB ' + weeksStr, '#f59e0b', '#0e0f12'));
        } else if (weekPlayoff) {
          // v0.10.29: Blue outline for ANY roster pairing in W16 or W17
          // (SF + Finals weeks). Covers same-team and opposing-team
          // overlaps. Falls below BRINGBACK in priority because BB has
          // the explicit high-total edge; WEEK 16/17 surfaces softer
          // playoff-week connections so the user can spot exposure.
          outlineTarget.style.boxShadow = 'inset 0 0 0 2px #3b82f6';
          outlineTarget.style.borderRadius = outlineTarget.style.borderRadius || '4px';
          if (getComputedStyle(outlineTarget).position === 'static') {
            outlineTarget.style.position = 'relative';
          }
          outlineTarget.dataset.mffOutline = 'weekplayoff';
          const weeksStr = weekPlayoff.hits.map(h => 'W' + h.wk).join('+');
          const detail = weekPlayoff.hits.map(h => {
            const same = h.sameTeam && h.sameTeam.length
              ? 'same team: ' + h.sameTeam.map(p => p.n).join(', ')
              : '';
            const opp = h.opposing && h.opposing.length
              ? 'vs ' + h.opp + ': ' + h.opposing.map(p => p.n).join(', ')
              : '';
            const ouStr = typeof h.total === 'number' ? ' (' + h.total.toFixed(1) + ' O/U)' : '';
            return 'W' + h.wk + ouStr + ' — ' + [same, opp].filter(Boolean).join('; ');
          }).join(' | ');
          outlineTarget.title = 'WEEK ' + weeksStr +
            ' — playoff-week roster overlap: ' + detail;
          outlineTarget.appendChild(makeRowLabel(weeksStr, '#3b82f6', '#fff'));
        } else if (teamSig) {
          // v0.9.74: TEAM — softer correlation than STACK. Subtle slate outline
          // and light-gray label so it reads as "nice-to-have" not "must-have".
          outlineTarget.style.boxShadow = 'inset 0 0 0 2px #94a3b8';
          outlineTarget.style.borderRadius = outlineTarget.style.borderRadius || '4px';
          if (getComputedStyle(outlineTarget).position === 'static') {
            outlineTarget.style.position = 'relative';
          }
          outlineTarget.dataset.mffOutline = 'team';
          outlineTarget.title = 'TEAM — same NFL team as: ' + teamSig.with.map(x => x.n).join(', ');
          const withName = (teamSig.with && teamSig.with[0] && teamSig.with[0].n)
            ? teamSig.with[0].n.split(' ').pop().toUpperCase()
            : '';
          outlineTarget.appendChild(makeRowLabel(
            'TEAM' + (withName ? ' ' + withName : ''),
            '#cbd5e1', '#1e293b'
          ));
        }
        // NEED branch removed in v0.10.29 — was crowding the playoff signals.
      }

      // Helper to build a styled badge with consistent visuals.
      const mkBadge = (className, text, title, colors) => {
        const b = document.createElement('span');
        b.className = className;
        b.dataset.mffDirect = '1';
        b.dataset.mffFor = player.n;
        b.textContent = text;
        b.title = title;
        b.style.cssText = [
          'display:inline-block',
          'margin-left:6px',
          'background:' + colors.bg,
          'color:' + colors.fg,
          'padding:1px 5px',
          'border-radius:3px',
          'font-size:10px',
          'font-weight:700',
          'letter-spacing:0.3px',
          'vertical-align:middle',
          'pointer-events:none',
          'line-height:1.4'
        ].join(';');
        return b;
      };

      // v0.10.21: split insertion done right —
      //   - Stat pills (%, PPG, age, ADP mvt) go INSIDE the name cell so
      //     they flow inline with the player name text on the same line.
      //   - Matchup pills (W15/16/17) go inline after the team cell, on
      //     the second line of the row (next to the team abbreviation).
      // The v0.10.16 attempt was almost right but appended to nameCell's
      // PARENT (a vertical flex column), which stacked the badges below
      // the name. Appending directly INSIDE nameCell fixes it.
      const nameBadges = [];
      const teamBadges = [];

      // v0.10.25: Stat pills (%, PPG, age, ADP mvt) only on PLAYER-POOL rows.
      // Roster rows show already-drafted players where these draft-decision
      // signals aren't useful — keep those rows uncluttered.
      if (!isRosterFormat) {
        if (exposure != null) {
          nameBadges.push(mkBadge(
            'mff-exposure',
            exposure.toFixed(0) + '%',
            'Your portfolio exposure: ' + exposure.toFixed(1) + '%',
            colorForExposure(exposure)
          ));
        }

        if (player.pPg != null) {
          nameBadges.push(mkBadge(
            'mff-ppg',
            player.pPg.toFixed(1) + 'p',
            'Projected PPG (1/2 PPR): ' + player.pPg.toFixed(1),
            colorForPpg(player.s, player.pPg)
          ));
        }

        if (player.age != null) {
          nameBadges.push(mkBadge(
            'mff-age',
            player.age + 'y',
            'Age: ' + player.age,
            colorForAge(player.s, player.age)
          ));
        }

        try {
          const fmt = state.isSuperflex ? 'sf' : 'bbm';
          const winDays = state.adpWindow || 7;
          const curAdp = (fmt === 'sf' ? player.sfa : player.udA);
          if (curAdp != null && state.adpHistory && state.adpHistory.length) {
            const mvt = _computeAdpDelta(player.n, curAdp, winDays, state.adpHistory, fmt);
            if (mvt && Math.abs(mvt.delta) >= 0.1) {
              const rising = mvt.delta > 0;
              const arrow = rising ? '▲' : '▼';
              const txt = arrow + ' ' + Math.abs(mvt.delta).toFixed(1);
              const colors = rising
                ? { bg: '#16a34a', fg: '#fff' }
                : { bg: '#dc2626', fg: '#fff' };
              const tooltip = 'ADP ' + (rising ? 'rose' : 'fell') + ' ' +
                              Math.abs(mvt.delta).toFixed(1) + ' over ' + winDays +
                              ' days (was ' + mvt.oldAdp.toFixed(1) +
                              ' on ' + mvt.oldDate + ')';
              nameBadges.push(mkBadge('mff-adp-mvt', txt, tooltip, colors));
            }
          }
        } catch (e) { /* silent */ }
      }

      // Playoff matchup pills next to team.
      if (typeof window.MFF_PLAYOFF_SOS === 'object'
          && (player.s === 'QB' || player.s === 'RB' || player.s === 'WR' || player.s === 'TE')) {
        const _teamRec = window.MFF_PLAYOFF_SOS[team];
        const _posRec = _teamRec ? _teamRec[player.s] : null;
        if (_posRec) {
          [15, 16, 17].forEach(w => {
            const m = _posRec[w];
            if (!m) return;
            const _arrow = m.home ? 'vs' : '@';
            const _host = _hostAbbr(team, m);
            const _isDome = _host && DOME_TEAMS.has(_host);
            const _txt = 'W' + w + ' ' + _arrow + m.opp + (_isDome ? ' Ⓓ' : '');
            const _tt = 'W' + w + ' ' + _arrow + ' ' + m.opp + ' — ' +
                        (m.label === 'E' ? 'easy' : m.label === 'M' ? 'mid' : 'hard') +
                        ' (rank ' + m.rank + '/32 for ' + player.s + ')' +
                        (typeof m.gameTotal === 'number' ? ', O/U ' + m.gameTotal : '') +
                        (typeof m.teamSpread === 'number'
                          ? ', ' + (m.teamSpread > 0 ? '+' : '') + m.teamSpread + ' sprd'
                          : '') +
                        (_isDome ? ' · dome (' + _host + ')' : '');
            const hex = (m.color || '#94a3b8').replace('#', '');
            const r = parseInt(hex.substr(0,2), 16), g = parseInt(hex.substr(2,2), 16), b = parseInt(hex.substr(4,2), 16);
            const colors = {
              bg: 'rgba(' + r + ',' + g + ',' + b + ',0.18)',
              fg: m.color,
            };
            teamBadges.push(mkBadge('mff-playoff-sos', _txt, _tt, colors));
          });
        }
      }

      // 1) Stat pills → INSIDE the name cell (siblings of the name text node).
      // This puts them inline with the name on the same horizontal line.
      const nameTextNode = findExactTextNode(el, name);
      if (nameBadges.length && nameTextNode && nameTextNode.parentNode) {
        const nameCell = nameTextNode.parentNode;
        for (const b of nameBadges) {
          nameCell.appendChild(b);
        }
      } else {
        // Fallback: append to row if we couldn't find the name cell.
        for (const b of nameBadges) el.appendChild(b);
      }

      // 2) Matchup pills → inline after the team abbreviation cell.
      const teamTextNode = findExactTextNode(el, team);
      if (teamBadges.length) {
        let insertParent, insertRef;
        if (teamTextNode && teamTextNode.parentNode && teamTextNode.parentNode.parentNode) {
          const teamCell = teamTextNode.parentNode;
          insertParent = teamCell.parentNode;
          insertRef = teamCell.nextSibling;
        } else {
          insertParent = el;
          insertRef = null;
        }
        for (const b of teamBadges) {
          if (insertRef) insertParent.insertBefore(b, insertRef);
          else insertParent.appendChild(b);
        }
      }

      el.dataset.mffExposureFor = player.n;
      injected++;
    }
    if (injected > 0) console.log('[MFF/decorate] injected', injected, 'badges');
  }

  // Wipe all MFF badges — used when the portfolio or roster changes so
  // stale values don't linger on virtualization-reused DOM nodes.
  function clearExposureBadges() {
    document.querySelectorAll('.mff-exposure, .mff-stack-badge, .mff-need-badge, .mff-ppg, .mff-age, .mff-adp-mvt, .mff-row-label, .mff-playoff-sos, .mff-playoff-row').forEach(b => b.remove());
    document.querySelectorAll('[data-mff-exposure-for]').forEach(el => {
      el.dataset.mffExposureFor = '';
    });
    // Strip any STACK / NEED row outlines so they recompute fresh on the
    // next decorate pass — otherwise a player who was a NEED earlier could
    // keep their red outline after you've drafted at that position.
    document.querySelectorAll('[data-mff-outline]').forEach(el => {
      el.style.boxShadow = '';
      el.dataset.mffOutline = '';
    });
  }

  // Run on interval. Use a short interval since virtualization adds/removes
  // rows quickly during scroll. The skip-if-already-decorated check keeps the
  // hot path cheap.
  let _exposureTimer = null;
  function startExposureDecorator() {
    if (_exposureTimer) return;
    _exposureTimer = setInterval(decoratePlayerList, 1500);
    // Run once immediately so the first paint isn't empty.
    setTimeout(decoratePlayerList, 200);
  }

  // Re-decorate after every render() — render fires on roster changes, slot
  // changes, format flip, etc. — so STACK / NEED signals update in real time
  // as you draft. Wipe first to clear stale flags from prior roster state.
  function refreshDecorations() {
    clearExposureBadges();
    setTimeout(decoratePlayerList, 50);
  }

  // ---------- v0.9.13: Sync portfolio directly from Underdog ----------
  // Talks to injected.js (MAIN world) over postMessage. Injected.js holds
  // the captured Bearer token and proxies the API request, then posts the
  // JSON back to us.
  function udFetch(endpoint, timeoutMs) {
    return new Promise((resolve) => {
      const reqId = 'mff_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8);
      const handler = (ev) => {
        if (!ev.data || ev.data.source !== 'mff-udsync-res') return;
        if (ev.data.reqId !== reqId) return;
        window.removeEventListener('message', handler);
        resolve(ev.data);
      };
      window.addEventListener('message', handler);
      window.postMessage({ source: 'mff-udsync-req', reqId, endpoint }, '*');
      setTimeout(() => {
        window.removeEventListener('message', handler);
        resolve({ error: 'Request timed out (15s)' });
      }, timeoutMs || 15000);
    });
  }

  // v0.9.29: ask injected.js for the captured Bearer token.
  function udGetToken(timeoutMs) {
    return new Promise((resolve) => {
      const reqId = 'tok_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8);
      const handler = (ev) => {
        if (!ev.data || ev.data.source !== 'mff-udsync-token-res') return;
        if (ev.data.reqId !== reqId) return;
        window.removeEventListener('message', handler);
        resolve(ev.data.token || null);
      };
      window.addEventListener('message', handler);
      window.postMessage({ source: 'mff-udsync-token', reqId }, '*');
      setTimeout(() => {
        window.removeEventListener('message', handler);
        resolve(null);
      }, timeoutMs || 1000);
    });
  }

  // v0.9.29: background-worker fetch — bypasses page CORS by running in
  // the extension's own origin context.
  // v0.17.6: reloading/updating the extension at chrome://extensions orphans
  // content scripts already injected into open tabs — chrome.runtime evaporates
  // and sendMessage throws. Detect the dead context and surface a plain-English
  // fix instead of the raw TypeError.
  const DEAD_CTX_MSG = 'Extension was updated — refresh this tab';
  function extAlive() {
    try { return !!(chrome && chrome.runtime && chrome.runtime.id); } catch (e) { return false; }
  }
  function bgFetch(url, token) {
    return new Promise((resolve) => {
      if (!extAlive()) return resolve({ ok: false, error: DEAD_CTX_MSG });
      try {
        chrome.runtime.sendMessage({ type: 'mff-bg-fetch', url, token }, (res) => {
          if (chrome.runtime.lastError) {
            resolve({ ok: false, error: chrome.runtime.lastError.message });
          } else {
            resolve(res || { ok: false, error: 'no response' });
          }
        });
      } catch (e) {
        resolve({ ok: false, error: extAlive() ? e.message : DEAD_CTX_MSG });
      }
    });
  }

  // v0.9.33: iframe-based auto-fetch. Background fetch returns 401 from
  // extension origin, but Underdog's own app (running inside an iframe of
  // the same origin) authenticates fine. We open a hidden iframe to
  // /draft/<id>; injected.js (now all_frames:true) runs in the iframe's
  // MAIN world, snoops the XHR response into the SHARED sessionStorage
  // (same origin, same tab), then we remove the iframe and move on.
  // v0.9.34: generic iframe-visit. Loads `url` in a hidden iframe; polls
  // sessionStorage cache for `cachePath` to appear; resolves when found
  // (success) or after timeoutMs (failure). Same-origin app.underdogfantasy.com
  // iframes are confirmed working — Underdog's SPA boots inside, makes its
  // own authenticated XHRs, our injected.js (all_frames:true) snoops them
  // into shared sessionStorage.
  function visitInIframe(url, cachePath, timeoutMs, settleMs) {
    return new Promise((resolve) => {
      let resolved = false;
      let poll = null;
      let timer = null;
      const finish = (ok) => {
        if (resolved) return;
        resolved = true;
        try { iframe.remove(); } catch (_) {}
        if (poll) clearInterval(poll);
        if (timer) clearTimeout(timer);
        resolve({ ok });
      };
      const iframe = document.createElement('iframe');
      iframe.src = url;
      // v0.9.39: removed `visibility:hidden` — Chrome heavily throttles
      // hidden iframes (timers + XHRs), which is the actual reason 42/49
      // draft fetches were timing out. Keeping the iframe rendered but
      // off-screen avoids the throttle. width/height kept generous so the
      // UD app doesn't bail on a "screen too small" guard.
      // v0.10.1: off-screen positioning (left/top:-99999px) is no longer
      // enough on the underdogsports.com domain — Chrome's intersection-
      // observer throttling treats the iframe as not visible and kills the
      // SPA boot before /v1/user/slates/<id>/tournament_rounds fires.
      // v0.10.2: opacity:0.001 + z-index:-1 also triggered throttling
      // (compositor treats near-zero opacity as invisible; z-index:-1 hides
      // it behind the body, counted as occluded). Bump opacity to 0.05 and
      // remove negative z-index so the iframe is genuinely visible to Chrome
      // — user sees a faint flicker during sync but the SPA actually boots.
      iframe.style.cssText = 'position:fixed;left:0;top:0;width:1200px;height:800px;border:0;opacity:0.05;pointer-events:none';
      document.body.appendChild(iframe);
      // v0.9.38/39: settle window — UD's draft page fires /v2/drafts/<id>
      // first, then /v1/slates/<sid>/players + appearances right after.
      // Close too soon and we never snoop the per-slate metadata, leaving
      // positions/teams unresolved. Wait `settle` ms after the trigger
      // path arrives. Default 2500ms.
      const settle = (settleMs == null) ? 2500 : settleMs;
      const totalTimeout = timeoutMs || 25000;
      poll = setInterval(async () => {
        const cached = await udBulk([cachePath]);
        if (cached[cachePath]) {
          clearInterval(poll); poll = null;
          // v0.9.39: kill the global timeout the moment we get the data.
          // Without this, on slow loads the timeout could fire DURING our
          // settle wait and report failure even though we have the bytes.
          if (timer) { clearTimeout(timer); timer = null; }
          setTimeout(() => finish(true), settle);
        }
      }, 500);
      timer = setTimeout(() => finish(false), totalTimeout);
    });
  }

  // v0.9.47: MAIN-world fetch via injected.js. The sidebar's ISOLATED-world
  // fetches go through the extension origin and UD returns 401 (no cookies).
  // injected.js runs in MAIN world with the page's full auth context — its
  // fetch behaves identically to UD's own SPA. Way faster + more reliable
  // than the iframe approach (~200-500ms per call vs 5-40s for iframes).
  function mainFetch(url, timeoutMs) {
    return new Promise((resolve) => {
      const reqId = 'mff_mf_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8);
      const handler = (ev) => {
        if (!ev.data || ev.data.source !== 'mff-mainfetch-res') return;
        if (ev.data.reqId !== reqId) return;
        window.removeEventListener('message', handler);
        resolve(ev.data);
      };
      window.addEventListener('message', handler);
      window.postMessage({ source: 'mff-mainfetch', reqId, url }, '*');
      setTimeout(() => {
        window.removeEventListener('message', handler);
        resolve({ ok: false, error: 'mainfetch-timeout' });
      }, timeoutMs || 10000);
    });
  }

  // v0.9.26: bulk request — returns { path: data } for all cached entries
  // whose path starts with any of the given prefixes.
  function udBulk(prefixes, timeoutMs) {
    return new Promise((resolve) => {
      const reqId = 'mff_bulk_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8);
      const handler = (ev) => {
        if (!ev.data || ev.data.source !== 'mff-udsync-bulk-res') return;
        if (ev.data.reqId !== reqId) return;
        window.removeEventListener('message', handler);
        resolve(ev.data.entries || {});
      };
      window.addEventListener('message', handler);
      window.postMessage({ source: 'mff-udsync-bulk', reqId, prefixes }, '*');
      setTimeout(() => {
        window.removeEventListener('message', handler);
        resolve({});
      }, timeoutMs || 5000);
    });
  }

  // Walk Underdog API response shapes looking for arrays of drafts that
  // each have a list of picks. Underdog has changed their schema before;
  // this version is defensive — if it can't find anything sensible, it
  // dumps the raw JSON to console so we can adjust the parser.
  function extractTeamsFromUDDrafts(payload) {
    const teams = [];
    if (!payload) return teams;

    // v0.9.23: also handle /completed_slates response shape (slates: [...]).
    const candidates = []
      .concat(Array.isArray(payload) ? [payload] : [])
      .concat(payload.drafts ? [payload.drafts] : [])
      .concat(payload.entries ? [payload.entries] : [])
      .concat(payload.draft_entries ? [payload.draft_entries] : [])
      .concat(payload.user_drafts ? [payload.user_drafts] : [])
      .concat(payload.slates ? [payload.slates] : [])
      .concat(payload.completed_slates ? [payload.completed_slates] : []);

    for (const arr of candidates) {
      if (!Array.isArray(arr)) continue;
      for (const draft of arr) {
        const team = extractTeamPicks(draft);
        if (team.length) teams.push(team);
      }
    }
    return teams;
  }

  function extractTeamPicks(draft) {
    const team = [];
    if (!draft || typeof draft !== 'object') return team;
    // Picks live under any of these keys depending on which endpoint:
    const picks = draft.picks || draft.draft_picks || draft.appearances ||
                  (draft.draft && (draft.draft.picks || draft.draft.draft_picks)) ||
                  draft.user_picks || [];
    if (!Array.isArray(picks)) return team;
    for (const p of picks) {
      const name =
        (p.appearance && (p.appearance.player_name || p.appearance.name)) ||
        (p.player && (p.player.full_name || ((p.player.first_name || '') + ' ' + (p.player.last_name || '')).trim())) ||
        p.player_name || p.name;
      if (name && typeof name === 'string') team.push(name.trim());
    }
    return team;
  }

  function buildPortfolioFromTeams(teams) {
    const numTeams = teams.length;
    const counts = {};
    const pairs = {};
    for (const team of teams) {
      const sorted = [...new Set(team)].sort();
      for (let i = 0; i < sorted.length; i++) {
        counts[sorted[i]] = (counts[sorted[i]] || 0) + 1;
        for (let j = i + 1; j < sorted.length; j++) {
          const k = sorted[i] + '|' + sorted[j];
          pairs[k] = (pairs[k] || 0) + 1;
        }
      }
    }
    const percent = {};
    for (const name in counts) percent[name] = (counts[name] / numTeams) * 100;
    return { teams, counts, pairs, percent, numTeams, syncedAt: Date.now() };
  }

  // v0.9.19: build the rich portfolio shape your MFF site uses for
  // _udPortfolio. Site shape (confirmed via live inspection):
  //   {
  //     drafts: [...],          // raw draft objects (we keep what UD gave us)
  //     players: { [name]: { pos, team, picks: [pickInDraft...], exposure (0-1),
  //                          avgPick, minPick, maxPick, count, draftIds } },
  //     numDrafts, totalInvestment, totalPicks
  //   }
  function buildSitePortfolio(udDrafts) {
    const drafts = [];
    const players = {};
    let totalInvestment = 0;
    let totalPicks = 0;

    for (const ud of (udDrafts || [])) {
      const draftId = ud.id || ud.draft_id || null;
      // v0.9.35: ud.entry_fee is now the proper looked-up fee, no longer
      // a fallback to entry_count. (Aggregator earlier in syncPortfolio…
      // already resolved this from /v2/entry_styles by entry_style_id.)
      const entryFee = parseFloat(ud.entry_fee != null ? ud.entry_fee : (ud.fee || 0)) || 0;
      totalInvestment += entryFee;
      const teamPicks = []; // [{name, pos, team, pick}]
      const picksArr = ud.picks || ud.draft_picks || [];
      for (const p of picksArr) {
        const name = (p.appearance && (p.appearance.player_name || p.appearance.name)) ||
                     (p.player && (p.player.full_name || ((p.player.first_name || '') + ' ' + (p.player.last_name || '')).trim())) ||
                     p.player_name || p.name;
        if (!name) continue;
        const pos = (p.appearance && p.appearance.position) ||
                    (p.player && p.player.position) ||
                    p.position || '';
        const team = (p.appearance && p.appearance.team_name) ||
                     (p.player && (p.player.team_name || p.player.team)) ||
                     p.team || '';
        const pick = parseInt(p.pick_number || p.number || p.pick || 0, 10) || null;
        teamPicks.push({ name: name.trim(), pos, team, pick });
        totalPicks++;
      }
      // v0.9.68: contest/team fields are now properly resolved upstream in
      // buildAggregatedFromBulk. ud.tournament = actual contest name; ud.teamName
      // = user's custom rename (or null). Pass through unchanged. ud.title is
      // back-compat and equals the contest name.
      const _udTournament = ud.tournament || ud.title || 'Underdog';
      const _udTeamName = ud.teamName || null;
      drafts.push({
        id: draftId,
        title: _udTournament,                 // back-compat: legacy code reads `title` as contest
        tournament: _udTournament,            // contest name (e.g. "The Field General") — used for grouping
        teamName: _udTeamName,                // user's renamed team (e.g. "FG LV/BIJ/AMON"), null if not renamed
        slateTitle: ud.slateTitle || null,    // e.g. "2026 Superflex Season"
        entry_fee: entryFee,
        fee: entryFee,
        size: ud.size || 12,
        phase: ud.phase || 'pre',
        picks: teamPicks,
        // v0.9.37: pass through full team data for site-side scoring.
        myEntryId: ud.myEntryId || null,
        allTeams: ud.allTeams || null,
        teamCount: ud.teamCount || 0
      });
      // Build per-player rollups
      for (const tp of teamPicks) {
        const key = tp.name;
        if (!players[key]) {
          players[key] = { pos: tp.pos, team: tp.team, draftIds: {}, picks: [],
                            exposure: 0, avgPick: 0, minPick: 0, maxPick: 0, count: 0 };
        }
        const pe = players[key];
        if (tp.pos && !pe.pos) pe.pos = tp.pos;
        if (tp.team && !pe.team) pe.team = tp.team;
        if (tp.pick != null) pe.picks.push(tp.pick);
        if (draftId) pe.draftIds[draftId] = true;
        pe.count++;
      }
    }

    // Finalize aggregates
    const numDrafts = drafts.length;
    for (const k of Object.keys(players)) {
      const pe = players[k];
      pe.exposure = numDrafts ? pe.count / numDrafts : 0;
      if (pe.picks.length) {
        pe.avgPick = pe.picks.reduce((a, b) => a + b, 0) / pe.picks.length;
        pe.minPick = Math.min.apply(null, pe.picks);
        pe.maxPick = Math.max.apply(null, pe.picks);
      }
    }
    return {
      drafts,
      players,
      numDrafts,
      totalInvestment,
      totalPicks,
      syncedAt: Date.now(),
      source: 'underdog-sync'
    };
  }

  // Merge two site-shape portfolios by draft id. Fresh wins for duplicates;
  // existing drafts not present in fresh are retained. This is what makes
  // mff_portfolio_sync cumulative across syncs — without it, an incremental
  // sync that only fetches 1 new draft would overwrite the storage entry
  // with just that 1 draft, and if the MFF tab missed the prior dispatch,
  // earlier drafts could be lost on the next mff-bridge replay.
  function _mergeSitePortfolios(existing, fresh) {
    if (!fresh || !Array.isArray(fresh.drafts)) return existing || fresh;
    if (!existing || !Array.isArray(existing.drafts) || !existing.drafts.length) return fresh;
    const byId = new Map();
    for (const d of existing.drafts) {
      if (d && d.id) byId.set(d.id, d);
    }
    for (const d of fresh.drafts) {
      if (d && d.id) byId.set(d.id, d);  // fresh overwrites stale by id
    }
    const allDrafts = Array.from(byId.values());
    const totalInvestment = allDrafts.reduce(
      (s, d) => s + (parseFloat(d.entry_fee != null ? d.entry_fee : (d.fee || 0)) || 0), 0
    );
    const totalPicks = allDrafts.reduce(
      (s, d) => s + ((Array.isArray(d.picks) && d.picks.length) || 0), 0
    );
    return Object.assign({}, fresh, {
      drafts: allDrafts,
      numDrafts: allDrafts.length,
      totalInvestment: totalInvestment,
      totalPicks: totalPicks,
      syncedAt: fresh.syncedAt || Date.now()
    });
  }

  // Push the site-shape portfolio through chrome.storage. mff-bridge picks
  // it up there and dispatches to the page when MFF site is open.
  // CUMULATIVE: reads existing mff_portfolio_sync first and merges fresh
  // drafts on top, so this storage entry always carries the union of every
  // sync the extension has ever done. Prevents data loss when the MFF tab
  // missed a prior dispatch and a later sync would otherwise overwrite the
  // entry down to just the latest sync's drafts.
  function publishPortfolioToSite(sitePortfolio) {
    if (!_isExtensionContextValid()) {
      console.warn('[MFF/sync] publish skipped — extension context invalidated. Refresh tab and re-sync.');
      return;
    }
    try {
      chrome.storage.local.get(['mff_portfolio_sync'], function (res) {
        const existing = res && res.mff_portfolio_sync;
        const merged = _mergeSitePortfolios(existing, sitePortfolio);
        chrome.storage.local.set({ mff_portfolio_sync: merged }, function () {
          if (chrome.runtime && chrome.runtime.lastError) {
            console.warn('[MFF/sync] storage.set error:', chrome.runtime.lastError.message);
            return;
          }
          const freshCount = (sitePortfolio.drafts && sitePortfolio.drafts.length) || 0;
          const totalCount = (merged.drafts && merged.drafts.length) || 0;
          const retained = Math.max(0, totalCount - freshCount);
          console.log('[MFF/sync] published site-shape portfolio:', freshCount,
                      'fresh +', retained, 'retained =', totalCount, 'total drafts');
        });
      });
    } catch (e) {
      console.warn('[MFF/sync] publish threw:', e && e.message);
    }
  }

  // v0.9.46: extracted from inside syncPortfolioFromUnderdog so we can run
  // it on partial bulks for incremental checkpoint publishes during a long
  // sync. Returns { aggregated, aggregatedRaw } — drafts without resolved
  // player metadata are silently skipped (they'll be picked up on the next
  // checkpoint after metadata is fetched).
  const _BB_VALID_POS = new Set(['QB', 'RB', 'WR', 'TE', 'K', 'DST', 'DEF', 'D/ST', 'FLEX']);
  function _normalizeBBPos(v) {
    if (!v || typeof v !== 'string') return '';
    const s = v.toUpperCase().trim();
    if (_BB_VALID_POS.has(s)) return s === 'DEF' || s === 'D/ST' ? 'DST' : s;
    const m = s.match(/^([A-Z]+)\d*$/);
    if (m && _BB_VALID_POS.has(m[1])) return m[1];
    return '';
  }

  // v0.9.67: shared fee resolver. Both buildAggregatedFromBulk (preview) and
  // the main syncPortfolio do fee resolution and were diverging — extracting
  // here so behavior is identical and one fix applies to both.
  //
  // KEY FIX: previously a draft whose entry_style_id WAS in esFeeMap but
  // mapped to fee 0 (legitimate freerolls like The Little Board) would fall
  // through to the meta.entry_fee / draft.entry_fee fallback chain because
  // the code tested `if (!fee)`. UD's tournament-rounds metadata does NOT
  // expose entry_fee for freerolls and may carry a non-zero "default" or
  // stale value for paid tournaments — leading to drafts displayed at the
  // wrong fee. This helper distinguishes:
  //   - cache HIT (entry_style_id resolved, fee is whatever it is, even 0)
  //   - cache MISS (entry_style_id not in esFeeMap → try fallbacks)
  // and logs the resolution path for every draft so the next time fees look
  // wrong we can read the console and see exactly what happened.
  //
  // Returns { fee, source, entryStyleId } where source ∈
  //   'entry_style_cache' | 'meta_fee' | 'draft_fee' | 'tournament_fee' | 'none'
  function _resolveDraftFee(draft, meta, esFeeMap, draftId) {
    const m = meta || {};
    const entryStyleId = m.entry_style_id || (draft && draft.entry_style_id) || null;
    let fee = 0;
    let source = 'none';
    if (entryStyleId && esFeeMap && esFeeMap.has(entryStyleId)) {
      fee = esFeeMap.get(entryStyleId);
      source = 'entry_style_cache';
      return { fee, source, entryStyleId };
    }
    // Cache MISS — try fallback chain. Legit $0 freerolls would have hit
    // the cache above, so a 0 here means we genuinely couldn't find a fee.
    const tryVals = [
      ['meta_fee', m.entry_fee != null ? m.entry_fee : m.fee],
      ['draft_fee', draft && (draft.entry_fee != null ? draft.entry_fee : draft.fee)],
      ['tournament_fee', draft && draft.tournament &&
                          (draft.tournament.entry_fee != null
                            ? draft.tournament.entry_fee
                            : draft.tournament.fee)]
    ];
    for (const [src, v] of tryVals) {
      const n = parseFloat(v);
      if (!isNaN(n) && n > 0) {
        fee = n;
        source = src;
        break;
      }
    }
    if (entryStyleId && source === 'none') {
      console.warn('[MFF/sync] fee unresolved — draft', draftId,
                   '· entry_style_id', entryStyleId,
                   'NOT in /v2/entry_styles cache; fallbacks empty');
    }
    return { fee, source, entryStyleId };
  }

  // v0.9.67: when a draft's entry_style_id wasn't returned by the bulk
  // /v2/entry_styles call, fetch the single record directly. UD exposes
  // /v2/entry_styles/<id> on the stats host. We backfill esFeeMap so the
  // ID resolves on subsequent calls in the same sync.
  async function _backfillEntryStyle(entryStyleId, esFeeMap, mainFetchFn) {
    if (!entryStyleId || !esFeeMap || esFeeMap.has(entryStyleId)) return false;
    if (typeof mainFetchFn !== 'function') return false;
    // v0.10.3: stats.* host stays on underdogfantasy.com — UD only migrated
    // the front-end domain, not the API hosts.
    const url = 'https://stats.underdogfantasy.com/v2/entry_styles/' + entryStyleId;
    try {
      const r = await mainFetchFn(url, 8000);
      if (!r || !r.ok || !r.data) return false;
      const es = r.data.entry_style || r.data;
      if (es && es.id) {
        const fee = parseFloat(es.fee) || 0;
        esFeeMap.set(es.id, fee);
        console.log('[MFF/sync] entry_style backfilled — id', es.id, 'fee $' + fee);
        return true;
      }
    } catch (e) {
      console.warn('[MFF/sync] entry_style backfill failed for', entryStyleId, e);
    }
    return false;
  }

  // v0.9.69: compute ADP movement vs N days ago for a player. Looks up
  // the snapshot whose date is closest to (today - windowDays) without
  // going more recent. Returns:
  //   { delta: number, oldAdp: number, oldDate: string, fromDate: string }
  // or null if no usable past snapshot exists.
  //
  // Convention: delta = oldAdp - currentAdp. Positive = player rising
  // (drafted earlier — "up 3 ADP" means ADP shrunk by 3). Negative =
  // player falling.
  function _computeAdpDelta(playerName, currentAdp, windowDays, history, format) {
    if (currentAdp == null || isNaN(currentAdp)) return null;
    if (!Array.isArray(history) || !history.length) return null;
    const fmt = format === 'sf' ? 'sf' : 'bbm';
    const now = new Date();
    const targetMs = now.getTime() - (windowDays * 86400 * 1000);
    // Walk history backwards (newest first), find oldest entry whose date
    // is on/before the target. If none old enough, take the OLDEST entry
    // we have so users with <N days of data still see something useful.
    let chosen = null;
    for (let i = history.length - 1; i >= 0; i--) {
      const entry = history[i];
      if (!entry || !entry.adps) continue;
      const ms = entry.capturedAt || (entry.date ? Date.parse(entry.date) : 0);
      if (!ms) continue;
      // Skip today's entry — comparing today vs today is delta 0.
      const todayStr = now.toISOString().slice(0, 10);
      if (entry.date === todayStr) continue;
      if (ms <= targetMs) { chosen = entry; break; }
      chosen = entry; // running oldest-so-far that's older than today
    }
    if (!chosen) return null;
    const past = chosen.adps[playerName];
    if (!past || past[fmt] == null) return null;
    const oldAdp = past[fmt];
    const delta = oldAdp - currentAdp;
    return { delta, oldAdp, oldDate: chosen.date, fromDate: chosen.date };
  }

  // v0.9.68: pure helper — walk bulk cache for /v1/slates/<sid>/.../appearances
  // entries, extract player_id → adp, then map player_id → name via the
  // /players responses for the same slate. Filter to portfolio players.
  // Returns { name: { bbm: number|null, sf: number|null } }. Slate type
  // (best ball vs superflex) inferred from the slate's description.
  function _extractAdpsFromBulk(bulk, portfolioPlayerNames) {
    if (!bulk) return {};
    // 1. Determine slate type for each slate_id we know about.
    //    v0.9.75: also accept /v2/slates/<sid> — the rich slate metadata
    //    moved to v2 (~1.7 MB blob), v1 still ships a 340 byte stub. Either
    //    is enough to register the slate id and infer bbm/sf from desc.
    const slateTypes = new Map();   // sid → 'sf' | 'bbm'
    for (const path of Object.keys(bulk)) {
      const m = path.match(/^\/v[12]\/slates\/([a-f0-9-]{20,})$/);
      if (!m) continue;
      const sd = bulk[path];
      const slate = sd && (sd.slate || sd);
      if (!slate) continue;
      const desc = ((slate.description || '') + ' ' + (slate.title || '')).toLowerCase();
      // Order matters: superflex slates contain "season" too.
      const type = /superflex/.test(desc) ? 'sf' : 'bbm';
      slateTypes.set(m[1], type);
    }
    // 2. Build player_id → full name from /v1/slates/<sid>/players
    //    v0.9.75: also accept /v2/slates/<sid>/players — UD migrated the
    //    players endpoint to v2; without this fallback `playerIdToName` was
    //    empty and every appearance mapped to undefined, making the daily
    //    ADP refresh log "no appearances cached" even when 800 KB of
    //    appearance data was sitting in sessionStorage.
    const playerIdToName = new Map();
    for (const path of Object.keys(bulk)) {
      if (!/^\/v[12]\/slates\/[a-f0-9-]{20,}\/players$/.test(path)) continue;
      const sd = bulk[path];
      const arr = sd && sd.players;
      if (!Array.isArray(arr)) continue;
      for (const p of arr) {
        if (!p || !p.id) continue;
        const fn = ((p.first_name || '') + ' ' + (p.last_name || '')).trim();
        if (fn) playerIdToName.set(p.id, fn);
      }
    }
    // 3. Walk all appearance paths, capture ADP. Be defensive about field
    //    names — UD has shipped 'adp', 'average_pick', and 'avg_pick' at
    //    different times. Take whichever is present and a positive number.
    //    v0.9.75: accept both /v1/ and /v2/ scoring_types appearance paths.
    const adps = {};
    let extractedCount = 0;
    let appearancePathCount = 0;
    let totalAppearances = 0;
    let unmatchedPlayerIds = 0;
    for (const path of Object.keys(bulk)) {
      const m = path.match(/^\/v[12]\/slates\/([a-f0-9-]{20,})\/scoring_types\/[a-f0-9-]+\/appearances$/);
      if (!m) continue;
      appearancePathCount++;
      const sid = m[1];
      const slateType = slateTypes.get(sid) || 'bbm';
      const sd = bulk[path];
      const arr = sd && sd.appearances;
      if (!Array.isArray(arr)) continue;
      totalAppearances += arr.length;
      for (const a of arr) {
        if (!a || !a.player_id) continue;
        const name = playerIdToName.get(a.player_id);
        if (!name) { unmatchedPlayerIds++; continue; }
        if (portfolioPlayerNames && !portfolioPlayerNames.has(name)) continue;
        // v0.9.75: UD migrated ADP into a nested `projection` object on
        // each appearance. New shape (May 2026):
        //   appearance.projection = { adp:"1.5", points:"294.9",
        //                             position_rank:"RB1", salary:"100", ... }
        // Values arrive as strings — parseFloat handles that. The legacy
        // top-level fields are kept as fallbacks for any cached responses
        // from older slates / snapshots.
        let raw = (a.projection && a.projection.adp != null) ? a.projection.adp
                : a.adp != null ? a.adp
                : a.average_pick != null ? a.average_pick
                : a.avg_pick != null ? a.avg_pick
                : (a.appearance_stat && a.appearance_stat.adp != null) ? a.appearance_stat.adp
                : null;
        const adp = parseFloat(raw);
        if (isNaN(adp) || adp <= 0) continue;
        if (!adps[name]) adps[name] = { bbm: null, sf: null };
        // Take min (best/most-current) ADP if multiple slates of same type.
        if (adps[name][slateType] == null || adp < adps[name][slateType]) {
          adps[name][slateType] = adp;
        }
        extractedCount++;
      }
    }
    // v0.9.75: surface diagnostics so the daily refresh can log exactly
    // where data dropped out (bulk size vs. slates discovered vs. players
    // mapped vs. appearances walked vs. ADPs extracted).
    return {
      adps,
      extractedCount,
      slateTypes: slateTypes.size,
      bulkKeys: Object.keys(bulk).length,
      playersMapSize: playerIdToName.size,
      appearancePathCount,
      totalAppearances,
      unmatchedPlayerIds,
      sampleBulkKeys: Object.keys(bulk).slice(0, 8)
    };
  }

  // v0.9.68: daily ADP refresh. Triggered on sidebar init when 24h+ has
  // passed since the last successful refresh. Pulls cached UD slate
  // appearance data from sessionStorage and extracts adp for every player
  // visible on those slates — no portfolio filter so the rankings page,
  // My Teams ADP val, and BB engine all see today's ADPs every day. Pushes
  // the snapshot via mff_player_adps_snapshot storage; mff-bridge.js relays
  // to the MFF site which overrides D[].udA/sfa and appends to a 30-day
  // Firestore history (so the site has fresh ADPs even before the user
  // opens UD on a given day, via _udLoadAdpSnapshot on page boot).
  // v0.9.73: removed portfolio-required gate — runs as long as any UD
  // slate cache is present.
  // Decide whether two ADP maps represent a real Underdog publish or are
  // effectively the same data. Returns true (= "capture this") when at least
  // a handful of players have moved by ≥0.05 ADP in either format, OR a
  // single player moved by ≥0.1. Calibrated against UD's typical overnight
  // ADP refresh which moves dozens of players by ≥0.1 in a batch.
  function _adpsDifferMaterially(prev, next) {
    if (!prev || !next) return true;
    let bigMoves = 0;     // ≥0.1 anywhere
    let smallMoves = 0;   // ≥0.05 anywhere
    for (const name of Object.keys(next)) {
      const a = next[name];
      const b = prev[name];
      if (!b) { bigMoves++; continue; }   // new player → counts as change
      const dBb = (a.bbm != null && b.bbm != null) ? Math.abs(a.bbm - b.bbm) : 0;
      const dSf = (a.sf  != null && b.sf  != null) ? Math.abs(a.sf  - b.sf ) : 0;
      const d = Math.max(dBb, dSf);
      if (d >= 0.1) bigMoves++;
      else if (d >= 0.05) smallMoves++;
      if (bigMoves >= 1) return true;     // any single big move qualifies
    }
    return smallMoves >= 5;               // or several small moves in aggregate
  }

  async function _dailyAdpRefreshIfNeeded() {
    try {
      console.log('[MFF/adp] _dailyAdpRefreshIfNeeded entered (sidebar v0.9.100)');
      // Trigger by VALUE CHANGE rather than by calendar/timer. UD republishes
      // ADPs on their own cadence (~daily, in the morning). We extract the
      // current ADPs from the slate cache and compare to the most recent
      // snapshot in storage; if anything material moved, save a fresh
      // snapshot. If nothing has moved, exit quietly. This makes the capture
      // automatically align with UD's update cycle — the first page load
      // after their morning publish triggers a save, and subsequent loads
      // before the next publish are no-ops.
      const now = Date.now();
      const todayStr = new Date(now).toISOString().slice(0, 10);
      const stored = await new Promise((r) => {
        try {
          chrome.storage.local.get(['mff_adp_last_refresh', 'mff_adp_history'], (res) => {
            r(res || {});
          });
        } catch (_) { r({}); }
      });
      const last = stored.mff_adp_last_refresh || 0;
      const historyIn = Array.isArray(stored.mff_adp_history) ? stored.mff_adp_history : [];
      const lastSnap = historyIn.length ? historyIn[historyIn.length - 1] : null;
      console.log('[MFF/adp] checking UD ADPs against last snapshot —',
                  'history depth:', historyIn.length,
                  ', last:', lastSnap ? lastSnap.date : 'never',
                  ', today:', todayStr,
                  ', last refresh:', last ? new Date(last).toISOString() : 'never');

      // v0.9.73: capture EVERY player's ADP from the UD slate cache, not just
      // ones in the user's portfolio. Rankings + My Teams both need fresh ADP
      // for every D[] entry to render correctly (ADP val, AVG BUILD, the live
      // rankings page numbers etc.). Pass null to _extractAdpsFromBulk to skip
      // the per-player filter. Portfolio is optional context; logged if present
      // so ops still know whose drafts are involved.
      const portfolio = await new Promise((r) => {
        try {
          chrome.storage.local.get(['mff_portfolio_sync'], (res) => {
            r(res && res.mff_portfolio_sync ? res.mff_portfolio_sync : null);
          });
        } catch (_) { r(null); }
      });
      const portfolioSize = (portfolio && portfolio.players)
        ? Object.keys(portfolio.players).length : 0;
      console.log('[MFF/adp] daily refresh — pulling ALL slate-cached ADPs (portfolio context:',
                  portfolioSize, 'players)');

      // Pull all slate-related cached entries from sessionStorage and extract
      // the current ADP set. Cheap (~tens of ms) when the cache is warm.
      //
      // Retry strategy:
      //   - If we ALREADY have a recent snapshot and the cache happens to be
      //     cold on this load, do a single attempt and exit quietly. Today's
      //     UI is already showing the previous snapshot's values; we'll catch
      //     UD's next publish on a future page load.
      //   - If we have NO history yet, retry up to 6× at 5s intervals so
      //     first-time users get a snapshot even if the slate XHRs are slow.
      const FRESH_RETRY_ATTEMPTS = 6;
      const RETRY_MS = 5000;
      const maxAttempts = lastSnap ? 1 : FRESH_RETRY_ATTEMPTS;
      let result = null;
      let playerCount = 0;
      for (let attempt = 1; attempt <= maxAttempts; attempt++) {
        const bulk = await udBulk(['/v1/slates/', '/v2/slates/']);
        result = _extractAdpsFromBulk(bulk, null);
        playerCount = Object.keys(result.adps).length;
        console.log('[MFF/adp] extraction stats — attempt ' + attempt + '/' + maxAttempts,
                    '· bulk keys:', result.bulkKeys,
                    '· slates:', result.slateTypes,
                    '· players map:', result.playersMapSize,
                    '· appearance paths:', result.appearancePathCount,
                    '· total appearances:', result.totalAppearances,
                    '· unmatched IDs:', result.unmatchedPlayerIds,
                    '· extracted ADPs:', playerCount);
        if (playerCount > 0) break;
        if (attempt < maxAttempts) {
          console.log('[MFF/adp] cache cold or empty — retrying in', RETRY_MS, 'ms');
          await new Promise(r => setTimeout(r, RETRY_MS));
        }
      }
      if (!playerCount) {
        console.log('[MFF/adp] no ADPs extracted after', maxAttempts,
                    'attempt(s). Sample cached keys:', result.sampleBulkKeys);
        if (!lastSnap) {
          console.log('[MFF/adp] visit a slate page on Underdog (e.g. open a draft pool) to populate the cache, then reload this tab');
        }
        return;
      }

      // Compare to most recent snapshot. If UD's values haven't moved since
      // our last capture, exit quietly — no need to write a redundant entry.
      // _adpsDifferMaterially returns true on the first run too (lastSnap is
      // null), so first-time users still capture.
      if (!_adpsDifferMaterially(lastSnap && lastSnap.adps, result.adps)) {
        console.log('[MFF/adp] UD ADPs unchanged vs', lastSnap.date, '— skipping save');
        return;
      }
      console.log('[MFF/adp] UD ADPs changed vs',
                  lastSnap ? lastSnap.date : '(no prior)',
                  '— extracted', playerCount, 'player ADPs across',
                  result.slateTypes, 'slate(s)');

      const snapshot = {
        date: todayStr,
        capturedAt: now,
        adps: result.adps
      };

      // Persist snapshot + append to 30-day history. Replaces today's entry
      // if one already exists (later-in-day publishes overwrite earlier ones).
      let history = historyIn.filter(s => s && s.date !== snapshot.date);
      history.push(snapshot);
      history.sort((a, b) => (a.date || '').localeCompare(b.date || ''));
      const trimmed = history.slice(-30);
      try {
        chrome.storage.local.set({
          mff_player_adps_snapshot: snapshot,
          mff_adp_history: trimmed,
          mff_adp_last_refresh: now
        });
        console.log('[MFF/adp] snapshot stored — site will pick up via storage listener · history depth', trimmed.length);
      } catch (e) {
        console.warn('[MFF/adp] storage.set failed:', e);
      }
    } catch (e) {
      console.warn('[MFF/adp] daily refresh error:', e);
    }
  }

  // v0.9.67: shared phase resolver. Inputs:
  //   slateDesc — lowercased "<description> <title>" of the slate
  //   titleLc   — lowercased tournament title
  // Returns one of 'pre' | 'nfl' | 'superflex'. Returns null if no signal
  // available (caller decides default).
  //
  // Order matters — superflex slates contain "season" in their description,
  // so /superflex/ has to win first. After that we check the explicit
  // pre-draft signal (covers UD's "2026 Pre-Draft Best Ball" wording), then
  // the season signal (covers post-NFL-draft "2026 Season"). Last-resort
  // tournament-name signals.
  function _resolvePhase(slateDesc, titleLc) {
    const sd = (slateDesc || '');
    const tl = (titleLc || '');
    if (/superflex/.test(sd) || /superflex/.test(tl) || /\bsf\b/.test(tl)) return 'superflex';
    if (/pre[\s-]?draft/.test(sd)) return 'pre';
    // "season" matches "2026 Season" and similar. Done after pre-draft so
    // a slate desc that mentions both (rare but possible) is still pre.
    if (/season/.test(sd)) return 'nfl';
    // No slate description but title hints at NFL season — fallback.
    if (/\bnfl\b/.test(sd) || /\bnfl\b/.test(tl)) return 'nfl';
    return null;  // no signal — caller defaults
  }

  function buildAggregatedFromBulk(bulk) {
    // Build appearance_id → player lookups from cached slate data
    const appearanceToPlayer = new Map();
    const playerById = new Map();
    const appearancePos = new Map();
    const appearanceProjTotal = new Map();
    for (const path of Object.keys(bulk)) {
      const d = bulk[path];
      if (!d) continue;
      if (path.endsWith('/appearances') || path.includes('/scoring_types/')) {
        const arr = d.appearances || [];
        for (const a of arr) {
          if (!a || !a.id) continue;
          if (a.player_id) appearanceToPlayer.set(a.id, a.player_id);
          const ap = a.position_id || a.position || (a.match_info && a.match_info.position) || '';
          const norm = _normalizeBBPos(ap);
          if (norm) appearancePos.set(a.id, norm);
          const projRaw = a.projected_points != null ? a.projected_points
                        : a.projection != null ? a.projection
                        : a.season_projected_points != null ? a.season_projected_points
                        : (a.appearance_stat && a.appearance_stat.projected_points != null)
                            ? a.appearance_stat.projected_points
                        : (a.stats && a.stats.projected_points != null)
                            ? a.stats.projected_points
                        : null;
          if (projRaw != null) {
            const v = parseFloat(projRaw);
            if (!isNaN(v) && v > 0) appearanceProjTotal.set(a.id, v);
          }
        }
      }
      if (path.endsWith('/players')) {
        const arr = d.players || [];
        for (const p of arr) {
          if (!p || !p.id) continue;
          const fullName = ((p.first_name || '') + ' ' + (p.last_name || '')).trim();
          // v0.9.59: position_name FIRST. UD's player object includes both
          // `position_id` (UUID like "ddd5757d-...") and `position_name`
          // ("WR" — clean code). Earlier we hit position_id first which
          // _normalizeBBPos correctly rejected as a UUID, but the chain
          // never reached position_name in time. Reorder: clean codes first,
          // UUID last as a token-of-effort fallback.
          const posVal = p.position_name || p.position || p.position_code ||
                         p.player_position || p.position_id || '';
          const teamVal = p.team_id || p.team || p.team_abbr || '';
          playerById.set(p.id, {
            name: fullName,
            pos: _normalizeBBPos(posVal),
            team: teamVal
          });
        }
      }
    }
    // Lookup maps
    const esFeeMap = new Map();
    const esCache = bulk['/v2/entry_styles'];
    if (esCache && Array.isArray(esCache.entry_styles)) {
      for (const es of esCache.entry_styles) {
        if (es && es.id) esFeeMap.set(es.id, parseFloat(es.fee) || 0);
      }
    }
    const draftMetaMap = new Map();
    for (const p of Object.keys(bulk)) {
      if (!p.includes('/tournament_rounds/') || !p.endsWith('/drafts')) continue;
      const arr = (bulk[p] && bulk[p].drafts) || [];
      for (const d of arr) {
        if (d && d.id) draftMetaMap.set(d.id, d);
      }
    }
    const teamMap = new Map();
    const teamsCache = bulk['/v1/teams'];
    if (teamsCache && Array.isArray(teamsCache.teams)) {
      for (const t of teamsCache.teams) {
        if (t && t.id) teamMap.set(t.id, t.abbr || t.short_name || t.name || '');
      }
    }
    // v0.9.59: slate_id → description (used for phase detection: pre-draft
    // best ball / superflex / post-NFL-draft season). Earlier phase logic
    // only looked at the tournament TITLE which is just "The Field General"
    // etc. — gives no signal about draft phase. The slate description has
    // the actual phase info ("2026 Pre-Draft Best Ball", "2026 Superflex
    // Season", "2026 Season").
    const slateDescMap = new Map();
    // v0.9.68: also capture the slate's actual title (e.g. "2026 Superflex Season")
    // to use as the contest name. The previous fallback chain ended up using the
    // user's custom team name (e.g. "FG LV/BIJ/AMON") because Underdog's
    // tournament_rounds endpoint returns the renamed team title in `meta.title`.
    const slateTitleMap = new Map();
    for (const p of Object.keys(bulk)) {
      // Match /v1/slates/<uuid> exactly (not /v1/slates/<uuid>/players etc.)
      if (!/^\/v1\/slates\/[a-f0-9-]{20,}$/.test(p)) continue;
      const sd = bulk[p];
      const slate = sd && (sd.slate || sd);
      if (slate && slate.id) {
        const text = ((slate.description || '') + ' ' + (slate.title || '')).toLowerCase();
        slateDescMap.set(slate.id, text);
        if (slate.title) slateTitleMap.set(slate.id, slate.title);
      }
    }

    // v0.9.68: Build a map of slate_id -> tournament name from the
    // /v1/user/slates/<id>/tournament_rounds responses. The tournament name
    // (e.g. "The Field General") lives only in tournament.rules_url; we extract
    // it from the slug. Fall back to slate.title if no tournament info found.
    function _udSlugToName(slug) {
      if (!slug) return null;
      // Strip trailing year (e.g. "the-field-general-2026" -> "the-field-general")
      const cleaned = String(slug).replace(/-?\d{4}$/, '');
      return cleaned.split('-').filter(Boolean)
        .map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
    }
    function _udTournamentNameFromUrl(url) {
      if (!url) return null;
      const m = String(url).match(/\/tournaments\/([a-z0-9-]+)/i);
      return m ? _udSlugToName(m[1]) : null;
    }
    // v0.10.4: map drafts to tournament names via tournament_round_id.
    // Earlier we keyed by slate_id, but a single slate (e.g. "NFL 2026
    // Season") contains multiple tournaments (BBM VII + The Puppy + …) and
    // the slate_id key collapsed them all into whichever tournament was
    // seen first — so Puppy drafts ended up labeled "Best Ball Mania Vii",
    // and the contest filter merged them into one chip. tournament_round_id
    // is unique per tournament-round, so this preserves each contest.
    const roundIdToTournamentName = new Map();
    for (const p of Object.keys(bulk)) {
      if (!/^\/v1\/user\/slates\/[a-f0-9-]{20,}\/tournament_rounds$/.test(p)) continue;
      const sd = bulk[p];
      const rounds = (sd && sd.tournament_rounds) || [];
      for (const round of rounds) {
        if (!round || !round.id) continue;
        const tName = (round.tournament && _udTournamentNameFromUrl(round.tournament.rules_url)) || null;
        if (tName) roundIdToTournamentName.set(round.id, tName);
      }
    }
    // draft_id -> tournament name. Walk the cached
    // /v1/user/tournament_rounds/<round_id>/drafts paths; the round_id in
    // the path tells us which tournament each draft belongs to.
    const draftIdToTournamentName = new Map();
    for (const p of Object.keys(bulk)) {
      const m = p.match(/^\/v1\/user\/tournament_rounds\/([a-f0-9-]{20,})\/drafts$/);
      if (!m) continue;
      const tName = roundIdToTournamentName.get(m[1]);
      if (!tName) continue;
      const arr = (bulk[p] && bulk[p].drafts) || [];
      for (const d of arr) {
        if (d && d.id) draftIdToTournamentName.set(d.id, tName);
      }
    }
    // Iterate cached /v2/drafts/<id> responses
    const aggregated = [];
    const aggregatedRaw = [];
    const _diag = { seen: 0, droppedNoPicks: [], droppedNoTeam: [], pickResolveStats: [] };
    for (const path of Object.keys(bulk)) {
      if (!path.startsWith('/v2/drafts/')) continue;
      const d = bulk[path];
      const draft = d && d.draft;
      if (!draft) continue;
      _diag.seen++;
      if (!Array.isArray(draft.picks)) {
        _diag.droppedNoPicks.push(draft.id || path);
        continue;
      }
      // v0.17.5: entrant usernames. The same /v2/drafts payload carries the
      // draft's entries (and sometimes a users[] block) alongside picks —
      // map entry_id -> username defensively (UD has changed shapes before):
      // embedded e.user first, then users[] matched by user_id. A miss just
      // leaves the site's "Opponent xxxxxx" fallback label.
      const entryUserMap = {};
      try {
        const usersById = new Map();
        [d.users, draft.users].forEach((ua) => {
          if (!Array.isArray(ua)) return;
          for (const u of ua) {
            if (u && u.id != null) usersById.set(u.id, u.username || u.display_name || null);
          }
        });
        const entryArr = draft.draft_entries || draft.entries || d.draft_entries || [];
        for (const e of entryArr) {
          if (!e || e.id == null) continue;
          const uname = (e.user && (e.user.username || e.user.display_name)) ||
                        (e.user_id != null ? usersById.get(e.user_id) : null) ||
                        e.username || null;
          if (uname) entryUserMap[e.id] = String(uname);
        }
      } catch (_) {}
      const teamsByEntry = new Map();
      let _pickTotal = 0, _pickResolved = 0;
      for (const p of draft.picks) {
        _pickTotal++;
        const playerId = appearanceToPlayer.get(p.appearance_id);
        const player = playerId ? playerById.get(playerId) : null;
        if (!player || !player.name) continue;
        _pickResolved++;
        const entryId = p.draft_entry_id;
        if (!teamsByEntry.has(entryId)) teamsByEntry.set(entryId, []);
        const pos = player.pos || appearancePos.get(p.appearance_id) || '';
        let team = '';
        if (player.team) {
          team = teamMap.get(player.team) ||
                 (typeof player.team === 'string' && player.team.length <= 4 ? player.team : '');
        }
        teamsByEntry.get(entryId).push({
          name: player.name,
          pos: pos,
          team: team,
          pick: p.number,
          weeklyScores: [],
          injuryStatus: null,
          udProj: appearanceProjTotal.get(p.appearance_id) || null
        });
      }
      const meta = draftMetaMap.get(draft.id) || {};
      const myEntryId = meta.user_draft_entry_id || null;
      const myTeamPicks = myEntryId && teamsByEntry.has(myEntryId)
        ? teamsByEntry.get(myEntryId)
        : (teamsByEntry.size ? teamsByEntry.values().next().value : null);
      if (!myTeamPicks) {
        _diag.droppedNoTeam.push({
          id: draft.id,
          slate_id: draft.slate_id,
          pickTotal: _pickTotal,
          pickResolved: _pickResolved,
          teamsByEntrySize: teamsByEntry.size,
          myEntryId: myEntryId
        });
        continue;
      }
      const allTeams = {};
      for (const [eid, picks] of teamsByEntry.entries()) {
        allTeams[eid] = {
          entryId: eid,
          username: entryUserMap[eid] || null,
          isMine: eid === myEntryId,
          pickCount: picks.length,
          picks: picks
        };
      }
      // v0.9.67: shared fee resolver — see _resolveDraftFee for behavior.
      const _feeRes = _resolveDraftFee(draft, meta, esFeeMap, draft.id);
      const fee = _feeRes.fee;
      // v0.9.68: meta.title / draft.title are the user's CUSTOM TEAM NAME on
      // Underdog (e.g. "FG LV/BIJ/AMON"), not the contest. The actual contest
      // comes from the slate (e.g. "2026 Superflex Season") and ideally the
      // tournament slug (e.g. "The Field General"). We compose: prefer
      // tournament name, then slate title, then fall back to the team title.
      const teamTitle = meta.title || draft.title || null;
      const slateTitle = slateTitleMap.get(draft.slate_id) || null;
      const tournamentName = draftIdToTournamentName.get(draft.id) || null;
      // Contest = best-available group name. Tournament name wins; otherwise slate.
      const contestName = tournamentName || slateTitle || 'Underdog';
      // teamName = custom rename only if it actually differs from the contest
      const teamName = (teamTitle && teamTitle !== contestName) ? teamTitle : null;
      const size = meta.entry_count || draft.entry_count || 12;
      // v0.9.67: shared phase resolver — see _resolvePhase. Returns null
      // when no signal available; default to 'pre' for backwards compat.
      const slateDesc = slateDescMap.get(draft.slate_id) || '';
      // v0.10.39: do NOT include teamTitle here — it's the user's CUSTOM team
      // name (e.g. "BBM SF/JJM/...") and would let user-typed "SF" abbreviations
      // misclassify BBM/Puppy/etc. as Superflex. slateDesc already contains
      // slate.description + slate.title lowercased (line ~4217), so it's the
      // single authoritative source. Keep slateTitle as a belt-and-suspenders
      // fallback for slates we have a title for but no description text.
      const titleLc = (slateTitle || '').toLowerCase();
      const phase = _resolvePhase(slateDesc, titleLc) || 'pre';
      aggregated.push(myTeamPicks.map(p => p.name));
      aggregatedRaw.push({
        id: draft.id,
        title: contestName,    // back-compat: legacy code uses `title` for the contest
        tournament: contestName, // explicit contest name (e.g. "The Field General")
        teamName: teamName,    // user's renamed team (e.g. "FG LV/BIJ/AMON"), null if not renamed
        slateTitle: slateTitle, // e.g. "2026 Superflex Season"
        entry_fee: fee,
        size: size,
        phase: phase,
        picks: myTeamPicks,
        myEntryId: myEntryId,
        allTeams: allTeams,
        teamCount: teamsByEntry.size
      });
    }
    // v0.10.10 diag: stash on window so it's readable from console regardless of
    // whether the warn fired. Wrapped in try/catch so any logging hiccup never
    // breaks the sync itself.
    try {
      const _emitted = aggregatedRaw.length;
      const _dropped = _diag.seen - _emitted;
      const _summary = {
        seen: _diag.seen,
        emitted: _emitted,
        dropped: _dropped,
        droppedNoPicks: _diag.droppedNoPicks,
        droppedNoTeam: _diag.droppedNoTeam,
        at: new Date().toISOString()
      };
      try { window.__mffSyncDiag = _summary; } catch (_) {}
      // v0.10.40: content scripts run in an isolated world, so `window.__mffSyncDiag`
      // set above is invisible to DevTools console (which inspects the page's main
      // world). v0.10.38 tried an inline-script injection but Underdog's CSP blocks
      // it. Use the existing main-world bridge (injected.js handles `mff-syncdiag`)
      // — postMessage is CSP-safe.
      try {
        window.postMessage({ source: 'mff-syncdiag', summary: _summary }, '*');
      } catch (_) {}
      if (_dropped > 0 || _diag.droppedNoPicks.length || _diag.droppedNoTeam.length) {
        console.warn('[MFF/sync] buildAggregatedFromBulk seen=' + _diag.seen +
                     ' emitted=' + _emitted + ' dropped=' + _dropped +
                     ' (noPicks=' + _diag.droppedNoPicks.length +
                     ', noTeam=' + _diag.droppedNoTeam.length +
                     ') — window.__mffSyncDiag has details');
      } else {
        console.log('[MFF/sync] buildAggregatedFromBulk seen=' + _diag.seen + ' emitted=' + _emitted + ' (no drops)');
      }
    } catch (e) {
      try { console.warn('[MFF/sync] diag logging error:', e && e.message); } catch (_) {}
    }
    return { aggregated, aggregatedRaw };
  }

  // v0.9.46: incremental checkpoint publish during long syncs. Builds the
  // current portfolio from whatever's in `bulk`, persists to extension
  // storage, and pushes to the MFF site so users see progress in real-time.
  // Drafts that haven't had their player metadata fetched yet are silently
  // skipped — they'll show up on the next checkpoint.
  function publishCheckpoint(bulk, label) {
    try {
      const { aggregated, aggregatedRaw } = buildAggregatedFromBulk(bulk);
      if (!aggregatedRaw.length) return 0;
      const portfolio = buildPortfolioFromTeams(aggregated);
      const sitePortfolio = buildSitePortfolio(aggregatedRaw);
      if (_isExtensionContextValid()) {
        try { chrome.storage.local.set({ mff_portfolio: portfolio }); } catch (_) {}
      }
      publishPortfolioToSite(sitePortfolio);
      console.log('[MFF/sync] checkpoint (' + (label || 'mid-sync') + '):',
                  aggregatedRaw.length, 'drafts published');
      return aggregatedRaw.length;
    } catch (e) {
      console.warn('[MFF/sync] checkpoint build error:', e && e.message);
      return 0;
    }
  }

  // Probe whether the MAIN-world hook is the current version. If
  // window.__mffUDCache isn't defined, the user's tab is running an old
  // injected.js (extension reloaded but tab not refreshed). Tell them
  // exactly what to do instead of the generic "no drafts" message.
  function probeMainHookVersion() {
    return new Promise((resolve) => {
      const reqId = 'probe_' + Date.now();
      const handler = (ev) => {
        if (!ev.data || ev.data.source !== 'mff-udsync-list-res') return;
        if (ev.data.reqId !== reqId) return;
        window.removeEventListener('message', handler);
        resolve({ ok: true, paths: ev.data.paths });
      };
      window.addEventListener('message', handler);
      window.postMessage({ source: 'mff-udsync-list', reqId }, '*');
      setTimeout(() => {
        window.removeEventListener('message', handler);
        resolve({ ok: false });
      }, 600);
    });
  }

  // v0.9.45: detect detached content scripts. After the user reloads the
  // extension at chrome://extensions, any tab that was open already has a
  // stale content script — its `chrome.runtime` and `chrome.storage`
  // handles are invalidated. Calls throw "Extension context invalidated."
  // The fix is always to refresh the tab; this helper short-circuits with
  // a clear message instead of letting the user wonder why sync silently
  // crashes mid-flight.
  function _isExtensionContextValid() {
    try {
      return !!(chrome && chrome.runtime && chrome.runtime.id);
    } catch (_) {
      return false;
    }
  }

  async function syncPortfolioFromUnderdog() {
    // v0.9.46: outer wrapper. If anything inside the sync throws (Underdog
    // network blip, iframe crash, transient extension-context loss), we
    // catch it here and try to save whatever progress we made. The inner
    // function does the actual work; this wrapper is just for guaranteed
    // partial-save and graceful error display.
    const _bulkRef = { current: null };  // populated by inner; closed-over for catch handler
    const status = document.getElementById('mff-sync-status');
    const btn = document.getElementById('mff-sync-btn');
    try {
      await _runSyncInner(_bulkRef);
    } catch (err) {
      console.warn('[MFF/sync] uncaught error:', err && (err.message || err));
      if (btn) btn.disabled = false;
      // Try to save whatever we have
      if (_bulkRef.current) {
        try {
          const saved = publishCheckpoint(_bulkRef.current, 'crash-recovery');
          if (status) {
            status.innerHTML =
              '<strong style="color:#f59e0b">Sync interrupted.</strong><br>' +
              'Saved ' + saved + ' draft' + (saved === 1 ? '' : 's') + ' from before the error.<br>' +
              '<span style="font-size:.7rem;color:var(--text2)">' + (err && err.message ? _esc(err.message) : 'Unknown error') + '</span><br>' +
              'Click Sync again to retry the rest.';
          }
        } catch (_) {
          if (status) status.textContent = 'Sync failed: ' + (err && err.message ? err.message : 'unknown');
        }
      } else if (status) {
        status.textContent = 'Sync failed: ' + (err && err.message ? err.message : 'unknown');
      }
    }
  }

  // Helper for crash-recovery message — escape HTML so error strings can't
  // accidentally render markup. (sidebar's normal _esc is in its own scope.)
  function _esc(s) {
    return String(s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  async function _runSyncInner(_bulkRef) {
    const status = document.getElementById('mff-sync-status');
    const btn = document.getElementById('mff-sync-btn');
    if (status) status.textContent = 'Syncing…';
    if (btn) btn.disabled = true;

    if (!_isExtensionContextValid()) {
      if (btn) btn.disabled = false;
      if (status) {
        status.innerHTML =
          '<strong style="color:#ef4444">Extension was reloaded.</strong><br>' +
          'This tab still has the old content script attached, so chrome.storage is dead. ' +
          '<strong>Hard-refresh this tab (Ctrl+Shift+R)</strong>, then click Sync.';
      }
      return;
    }

    // Pre-flight: is the v0.9.23+ hook actually loaded on this tab?
    const probe = await probeMainHookVersion();
    if (!probe.ok) {
      if (btn) btn.disabled = false;
      if (status) {
        status.innerHTML =
          '<strong style="color:#ef4444">Hook not loaded.</strong><br>' +
          'You reloaded the extension but this Underdog tab is still on the old version. ' +
          '<strong>Refresh this tab (F5)</strong>, then navigate to /active and /completed, then click Sync.';
      }
      return;
    }

    // v0.9.31: HYBRID sync. The page-snoop cache is the primary source
    // (the page's auth Just Works). Background fetch is only a fallback
    // for endpoints not yet visited in the user's session.
    const token = await udGetToken();
    // v0.10.1: UD migrated front-end from underdogfantasy.com →
    // underdogsports.com but kept the API hosts on underdogfantasy.com.
    // v0.10.3: confirmed via DNS — api.underdogsports.com / stats.under-
    // dogsports.com do NOT exist (ERR_NAME_NOT_RESOLVED). Only the front-
    // end app.* domain moved. So API/STATS stay locked to fantasy.com;
    // only APP follows the current tab so iframes stay same-origin with
    // the sidebar parent (required for the sessionStorage snoop).
    const API = 'https://api.underdogfantasy.com';
    // v0.9.57: Underdog uses TWO API hosts. User-scoped data (drafts, slates
    // index, profile) lives on api.*; reference data (slate-level players,
    // appearances, scoring_types, entry_styles, teams) lives on stats.*.
    // Hitting api.* for stats.* endpoints returns 404 — which was breaking
    // metadata fetching even though drafts themselves loaded fine. Verified
    // live: /v1/slates/<id>/players → api.* 404, stats.* 200 OK.
    const STATS = 'https://stats.underdogfantasy.com';
    const APP = /underdogsports\.com$/.test(location.hostname)
      ? 'https://app.underdogsports.com'
      : 'https://app.underdogfantasy.com';
    function _resolveUDHost(path) {
      // Path-pattern → host. Default api.* for anything user-scoped.
      // v0.9.75: accept v1 OR v2 slate paths — UD moved /slates/<id>/players
      // to /v2/ but kept appearances/metadata on /v1/. Both still live on
      // stats.* (api.* returns 404).
      if (/^\/v[12]\/slates\/[^/]+($|\/)/.test(path)) return STATS;  // /v[12]/slates/<id>/players, /v1/slates/<id>/scoring_types/.../appearances, etc.
      if (path.startsWith('/v1/teams')) return STATS;
      if (path.startsWith('/v1/scoring_types')) return STATS;
      if (path.startsWith('/v1/contest_styles')) return STATS;
      if (path.startsWith('/v1/lineup_statuses')) return STATS;
      if (path.startsWith('/v1/slots')) return STATS;
      if (path.startsWith('/v2/sports')) return STATS;
      if (path.startsWith('/v2/entry_styles')) return STATS;
      return API;
    }
    function _udUrl(path) { return _resolveUDHost(path) + path; }
    const bulk = {};
    // v0.9.46: expose bulk to the outer wrapper so a crash can still save
    // whatever progress we made. The wrapper holds a reference; we point
    // it at the local bulk so any subsequent error handler can read it.
    if (_bulkRef) _bulkRef.current = bulk;

    // v0.9.57: try local bulk → page-snoop cache → mainfetch (with proper
    // host resolution + UD headers + query params). The old bgFetch path
    // returns 401/404 because it can't replicate UD's full request shape.
    // mainfetch via injected.js mimics UD's own SPA exactly so it just works.
    async function getEndpoint(path, fullUrl) {
      if (bulk[path]) {
        return { ok: true, data: bulk[path], source: 'pre-cache' };
      }
      const cached = await udBulk([path]);
      if (cached[path]) {
        bulk[path] = cached[path];
        console.log('[MFF/sync] cache hit:', path);
        return { ok: true, data: cached[path], source: 'cache' };
      }
      // Use the host-aware URL if caller provided just the path
      const url = (fullUrl && fullUrl.startsWith('http')) ? fullUrl : _udUrl(path);
      const mf = await mainFetch(url, 12000);
      if (mf.ok && mf.data) {
        bulk[path] = mf.data;
        return { ok: true, data: mf.data, source: 'mainfetch' };
      }
      console.log('[MFF/sync] mainfetch failed:', path, mf.status || mf.error);
      return { ok: false, status: mf.status, error: mf.error || 'mainfetch-failed' };
    }

    // v0.9.36: read existing draft IDs from chrome.storage (populated by
    // mff-bridge from the site's _udPortfolio). We'll skip these during
    // discovery so subsequent syncs only process new drafts.
    const existingDraftIds = await new Promise((resolve) => {
      try {
        chrome.storage.local.get(['mff_existing_draft_ids'], (res) => {
          resolve(new Set(res && Array.isArray(res.mff_existing_draft_ids) ? res.mff_existing_draft_ids : []));
        });
      } catch (e) { resolve(new Set()); }
    });
    if (existingDraftIds.size) {
      console.log('[MFF/sync] will skip', existingDraftIds.size, 'drafts already in portfolio');
    }

    if (status) status.textContent = 'Loading cached data…';

    // v0.9.32: pre-load EVERYTHING already snooped from the page. The
    // page's authenticated XHRs caught a lot of useful data — appearances,
    // players, slate metadata — that the background fetch can't replicate
    // (it 401s or 404s on the same endpoints). Pre-loading means even if
    // we never explicitly request a path, if the page snooped it, we use it.
    const preCache = await udBulk(['/v1/slates/', '/v2/slates/', '/v1/user/', '/v2/drafts/', '/v2/user/', '/v4/user/', '/v2/entry_styles', '/v1/teams']);
    Object.keys(preCache).forEach(p => { bulk[p] = preCache[p]; });
    console.log('[MFF/sync] pre-loaded', Object.keys(preCache).length, 'cached endpoints');

    // v0.9.38: ensure /v2/entry_styles is cached. UD only fetches it when
    // the user lands on a contest lobby; pure /completed walks never hit
    // it, so fees end up at $0. One quick warmup iframe to the best-ball
    // lobby triggers UD's own authenticated XHR for entry_styles, which
    // injected.js snoops into our cache. No-op if already cached.
    if (!bulk['/v2/entry_styles']) {
      if (status) status.textContent = 'Loading entry-style metadata…';
      try {
        await visitInIframe(APP + '/lobby/best-ball',
                            '/v2/entry_styles', 8000, 1500);
      } catch (_) {}
      const refreshedEs = await udBulk(['/v2/entry_styles']);
      if (refreshedEs['/v2/entry_styles']) {
        bulk['/v2/entry_styles'] = refreshedEs['/v2/entry_styles'];
        console.log('[MFF/sync] entry_styles warmed via lobby iframe');
      } else {
        // Fallback URL — older UD apps used /best-ball as the route
        try {
          await visitInIframe(APP + '/best-ball',
                              '/v2/entry_styles', 8000, 1500);
        } catch (_) {}
        const refreshedEs2 = await udBulk(['/v2/entry_styles']);
        if (refreshedEs2['/v2/entry_styles']) {
          bulk['/v2/entry_styles'] = refreshedEs2['/v2/entry_styles'];
          console.log('[MFF/sync] entry_styles warmed via /best-ball iframe');
        }
      }
    }

    if (status) status.textContent = 'Discovering drafts…';

    // 1. List of slates the user has played
    const slatesRes = await getEndpoint('/v2/user/completed_slates', API + '/v2/user/completed_slates');
    if (!slatesRes.ok) {
      if (status) {
        status.innerHTML =
          '<strong style="color:#ef4444">Sync failed</strong><br>' +
          'Need /completed_slates in cache. ' +
          '<a href="' + APP + '/completed" target="_blank" style="color:#fbbf24">' +
          'Open /completed</a> on Underdog, then click Sync again.';
      }
      if (btn) btn.disabled = false;
      return;
    }
    const slates = (slatesRes.data && slatesRes.data.slates) || [];
    bulk['/v2/user/completed_slates'] = slatesRes.data;
    console.log('[MFF/sync] found', slates.length, 'slates (' + slatesRes.source + ')');

    // Also include active_drafts (cache or fetch)
    const activeRes = await getEndpoint('/v4/user/active_drafts', API + '/v4/user/active_drafts');
    if (activeRes.ok) bulk['/v4/user/active_drafts'] = activeRes.data;

    // 2. For each slate → tournament_rounds → drafts → /v2/drafts/<id>
    let draftsFetched = 0;
    let totalDraftsExpected = 0;
    const allDraftIds = [];
    const slateIds = new Set();

    let cachedDraftCount = 0;
    let bgFetchedDraftCount = 0;
    let skippedExisting = 0;

    // v0.9.34: helper — try cache → bg → iframe (visit Underdog page so its
    // own app makes the request). Iframes are the reliable path since
    // background fetch 401s for most endpoints.
    // v0.9.38: settleMs lets callers tell visitInIframe how long to keep
    // the iframe alive AFTER the requested path lands. /v2/drafts/<id>
    // pages also fire /v1/slates/<sid>/players + appearances right after,
    // and we want those snooped too. Lookup-only endpoints (tournament
    // listings) don't need a settle so we pass 0.
    // v0.9.39: one automatic retry on iframe timeout. Cold cache + a heavy
    // UD page can take 20+ seconds; a single transient timeout shouldn't
    // permanently exclude that draft from the portfolio.
    // v0.9.48: rate-limit shared state. v0.9.52: also a circuit breaker —
    // after N consecutive 401/403s, we stop trying mainfetch for the rest
    // of the sync run. Each failed mainfetch was wasting 5.5s on backoff
    // before falling to iframe; bypassing mainfetch lets iframes have the
    // floor immediately.
    let _lastMainFetchAt = 0;
    let _mainFetchBackoffMs = 0;
    let _mainFetchConsecFails = 0;
    let _mainFetchDisabled = false;
    const MAINFETCH_BASE_DELAY_MS = 1500;
    const MAINFETCH_MAX_BACKOFF_MS = 15000;
    const MAINFETCH_FAILS_BEFORE_DISABLE = 3;
    async function _pacedMainFetch(fullUrl) {
      if (_mainFetchDisabled) {
        return { ok: false, error: 'mainfetch-disabled-this-run' };
      }
      const now = Date.now();
      const elapsed = now - _lastMainFetchAt;
      const need = MAINFETCH_BASE_DELAY_MS + _mainFetchBackoffMs;
      if (_lastMainFetchAt && elapsed < need) {
        await new Promise(r => setTimeout(r, need - elapsed));
      }
      _lastMainFetchAt = Date.now();
      const r = await mainFetch(fullUrl, 12000);
      if (r.ok) {
        _mainFetchBackoffMs = Math.max(0, _mainFetchBackoffMs - 1000);
        _mainFetchConsecFails = 0;
      } else if (r.status === 401 || r.status === 429 || r.status === 403) {
        _mainFetchBackoffMs = Math.min(
          MAINFETCH_MAX_BACKOFF_MS,
          (_mainFetchBackoffMs || 1000) * 2
        );
        _mainFetchConsecFails++;
        console.log('[MFF/sync] mainfetch', r.status, '(' + _mainFetchConsecFails + ' consec fails)');
        if (_mainFetchConsecFails >= MAINFETCH_FAILS_BEFORE_DISABLE) {
          _mainFetchDisabled = true;
          console.log('[MFF/sync] mainfetch disabled for rest of run — going iframe-only');
        }
      } else {
        _mainFetchConsecFails++;
      }
      return r;
    }

    async function getOrIframe(path, fullUrl, iframeUrl, settleMs) {
      // 1. Cache hit (instant)
      const e = await getEndpoint(path, fullUrl);
      if (e.ok) return e;

      // 2. mainfetch (skipped after circuit breaker trips)
      const mf = await _pacedMainFetch(fullUrl);
      if (mf.ok && mf.data) {
        bulk[path] = mf.data;
        return { ok: true, data: mf.data, source: 'mainfetch' };
      }

      // 3. Iframe fallback
      if (!iframeUrl) return { ok: false, error: mf.error || 'no-iframe-url' };
      for (let attempt = 1; attempt <= 2; attempt++) {
        const r = await visitInIframe(iframeUrl, path, 40000, settleMs);
        if (r.ok) {
          const refreshed = await udBulk([path]);
          if (refreshed[path]) {
            bulk[path] = refreshed[path];
            const src = attempt === 1 ? 'iframe' : 'iframe-retry';
            console.log('[MFF/sync] ✓', src, 'for', path);
            return { ok: true, data: refreshed[path], source: src };
          }
        }
        if (attempt < 2) await new Promise(r => setTimeout(r, 1500));
      }
      console.log('[MFF/sync] ✗ iframe timeout for', path);
      return { ok: false, error: 'iframe-timeout' };
    }

    // v0.10.47: tournament-round drafts are PAGINATED — the "Load more" button
    // on Underdog's "Your teams" list fires .../drafts?page=N. getOrIframe only
    // gets the first page (plus any pages the user manually loaded, which
    // injected.js now merges into one cache entry). To capture every team
    // without the user clicking Load more, actively walk page=2.. via mainfetch
    // and merge each page's drafts in. Stops when a page returns no NEW drafts
    // (handles both ?page= pagination and APIs that ignore the param), when the
    // response meta says there's no next page, or at a hard cap.
    function _metaSaysDone(data) {
      const m = data && data.meta;
      if (!m) return false;
      if ('next_page' in m) return m.next_page == null || m.next_page === false;
      if (m.current_page != null && m.total_pages != null) return m.current_page >= m.total_pages;
      if ('has_more' in m) return !m.has_more;
      return false;
    }
    async function fetchAllRoundDrafts(roundId, slateId) {
      const basePath = '/v1/user/tournament_rounds/' + roundId + '/drafts';
      const baseUrl = API + basePath;
      const first = await getOrIframe(basePath, baseUrl, APP + '/completed/' + slateId + '/tr/' + roundId, 0);
      if (!first.ok) return first;
      const merged = first.data || {};
      if (!Array.isArray(merged.drafts)) merged.drafts = [];
      const seen = new Set(merged.drafts.map(d => d && d.id).filter(Boolean));
      const MAX_PAGES = 50;
      let page = 2;
      let done = _metaSaysDone(merged);
      while (!done && page <= MAX_PAGES && !_mainFetchDisabled) {
        const pageUrl = baseUrl + (baseUrl.indexOf('?') >= 0 ? '&' : '?') + 'page=' + page;
        const mf = await _pacedMainFetch(pageUrl);
        if (!mf.ok || !mf.data) break;
        const arr = Array.isArray(mf.data.drafts) ? mf.data.drafts : [];
        let added = 0;
        for (const d of arr) {
          if (d && d.id && !seen.has(d.id)) { seen.add(d.id); merged.drafts.push(d); added++; }
        }
        console.log('[MFF/sync] round', roundId, 'page', page, '→ +' + added, 'new drafts (' + arr.length + ' returned)');
        if (added === 0) break;            // param ignored, or no more pages
        if (_metaSaysDone(mf.data)) break;
        page++;
      }
      return { ok: true, data: merged, source: first.source };
    }

    for (let i = 0; i < slates.length; i++) {
      const slate = slates[i];
      if (!slate || !slate.id) continue;
      slateIds.add(slate.id);
      if (status) status.textContent = 'Listing slate ' + (i + 1) + '/' + slates.length + '…';
      const trRes = await getOrIframe(
        '/v1/user/slates/' + slate.id + '/tournament_rounds',
        API + '/v1/user/slates/' + slate.id + '/tournament_rounds',
        APP + '/completed/' + slate.id + '/',
        0
      );
      if (!trRes.ok) {
        console.log('[MFF/sync] could not get tournament_rounds for slate', slate.id);
        continue;
      }
      bulk['/v1/user/slates/' + slate.id + '/tournament_rounds'] = trRes.data;
      const rounds = (trRes.data && trRes.data.tournament_rounds) || [];
      for (const round of rounds) {
        if (!round || !round.id) continue;
        if (status) status.textContent = 'Listing slate ' + (i + 1) + '/' + slates.length + ' tournament…';
        const dRes = await fetchAllRoundDrafts(round.id, slate.id);
        if (!dRes.ok) continue;
        bulk['/v1/user/tournament_rounds/' + round.id + '/drafts'] = dRes.data;
        const dArr = (dRes.data && dRes.data.drafts) || [];
        for (const d of dArr) {
          if (!d || !d.id) continue;
          if (existingDraftIds.has(d.id)) {
            skippedExisting++;
            continue;
          }
          allDraftIds.push(d.id);
          totalDraftsExpected++;
        }
      }
    }

    console.log('[MFF/sync] discovered', allDraftIds.length, 'NEW drafts',
                '(skipped', skippedExisting, 'already in portfolio across', slates.length, 'slates)');

    // v0.10.4: backfill missing entry_style fees BEFORE the per-draft fetch
    // loop so every checkpoint publish has correct fees. UD's /v2/entry_styles
    // bulk endpoint only returns ACTIVE tournaments; closed-tournament drafts
    // (and any contest a particular user plays that isn't in the site's
    // hardcoded _UD_FEE_DEFAULTS map) need /v2/entry_styles/<id> hit directly.
    // This makes the sync work for any user on any tournament — not just the
    // ones Jack plays.
    if (status) status.textContent = 'Resolving entry fees…';
    const _esFeeMap = new Map();
    const _esCache = bulk['/v2/entry_styles'];
    if (_esCache && Array.isArray(_esCache.entry_styles)) {
      for (const es of _esCache.entry_styles) {
        if (es && es.id) _esFeeMap.set(es.id, parseFloat(es.fee) || 0);
      }
    }
    const _missingEsIds = new Set();
    for (const path of Object.keys(bulk)) {
      if (!path.includes('/tournament_rounds/') || !path.endsWith('/drafts')) continue;
      const arr = (bulk[path] && bulk[path].drafts) || [];
      for (const d of arr) {
        const esid = d && d.entry_style_id;
        if (esid && !_esFeeMap.has(esid)) _missingEsIds.add(esid);
      }
    }
    if (_missingEsIds.size) {
      console.log('[MFF/sync] backfilling', _missingEsIds.size, 'missing entry_style fees…');
      let _n = 0;
      for (const esid of _missingEsIds) {
        _n++;
        if (status) status.textContent = 'Resolving entry fees ' + _n + '/' + _missingEsIds.size + '…';
        await _backfillEntryStyle(esid, _esFeeMap, mainFetch);
      }
      // Persist resolved fees back into bulk so buildAggregatedFromBulk
      // (called from each checkpoint and the final publish) sees them.
      const _existingIds = new Set(
        (_esCache && Array.isArray(_esCache.entry_styles))
          ? _esCache.entry_styles.map(e => e && e.id).filter(Boolean)
          : []
      );
      const _newEntries = [];
      for (const [id, fee] of _esFeeMap.entries()) {
        if (!_existingIds.has(id)) _newEntries.push({ id, fee });
      }
      if (_newEntries.length) {
        if (_esCache && Array.isArray(_esCache.entry_styles)) {
          _esCache.entry_styles.push(..._newEntries);
        } else {
          bulk['/v2/entry_styles'] = { entry_styles: _newEntries };
        }
      }
    }

    const CHECKPOINT_INTERVAL = 10;
    const _csMap = new Map();
    let _csFetched = false;
    async function _ensureContestStylesCache() {
      if (_csFetched) return;
      _csFetched = true;
      const cs = await getEndpoint('/v1/contest_styles', _udUrl('/v1/contest_styles'));
      if (cs.ok && cs.data && Array.isArray(cs.data.contest_styles)) {
        for (const c of cs.data.contest_styles) {
          if (c && c.id && c.scoring_type_id) _csMap.set(c.id, c.scoring_type_id);
        }
      }
    }
    const fetchedSlatesForMeta = new Set();
    async function _fetchSlateMetadata(sid) {
      if (!sid || fetchedSlatesForMeta.has(sid)) return;
      await _ensureContestStylesCache();
      // v0.10.11: getEndpoint only (cache + mainfetch). Iframe attempts here
      // would stall every checkpoint by up to 80s per failed slate. Slates
      // that don't resolve via mainfetch get one iframe shot at the very end
      // of sync (see _ironSlateMetadata below).
      let pr = await getEndpoint('/v2/slates/' + sid + '/players', _udUrl('/v2/slates/' + sid + '/players'));
      let _gotPlayers = false;
      if (pr.ok) {
        bulk['/v2/slates/' + sid + '/players'] = pr.data;
        _gotPlayers = true;
      } else {
        pr = await getEndpoint('/v1/slates/' + sid + '/players', _udUrl('/v1/slates/' + sid + '/players'));
        if (pr.ok) {
          bulk['/v1/slates/' + sid + '/players'] = pr.data;
          _gotPlayers = true;
        }
      }
      // Only mark slate done if we actually got players — otherwise a later
      // retry (next checkpoint or the post-loop iframe sweep) can take another
      // shot. Without this, a failed-fetch slate stays unfetched forever and
      // every draft on it gets silently dropped in buildAggregatedFromBulk.
      if (_gotPlayers) fetchedSlatesForMeta.add(sid);
      const sm = await getEndpoint('/v1/slates/' + sid, _udUrl('/v1/slates/' + sid));
      let scoringTypeId = null;
      if (sm.ok && sm.data) {
        bulk['/v1/slates/' + sid] = sm.data;
        const slate = sm.data.slate || sm.data;
        if (slate && Array.isArray(slate.contest_style_ids)) {
          for (const csId of slate.contest_style_ids) {
            if (_csMap.has(csId)) { scoringTypeId = _csMap.get(csId); break; }
          }
        }
        if (!scoringTypeId && slate && slate.contest_styles && slate.contest_styles[0]) {
          scoringTypeId = slate.contest_styles[0].scoring_type_id;
        }
        if (!scoringTypeId && slate && slate.scoring_type_id) scoringTypeId = slate.scoring_type_id;
      }
      if (scoringTypeId) {
        const ap = await getEndpoint(
          '/v1/slates/' + sid + '/scoring_types/' + scoringTypeId + '/appearances',
          _udUrl('/v1/slates/' + sid + '/scoring_types/' + scoringTypeId + '/appearances')
        );
        if (ap.ok) bulk['/v1/slates/' + sid + '/scoring_types/' + scoringTypeId + '/appearances'] = ap.data;
      }
    }

    for (let i = 0; i < allDraftIds.length; i++) {
      const did = allDraftIds[i];
      if (status) {
        status.textContent = 'Fetching draft ' + (i + 1) + '/' + allDraftIds.length;
      }
      const r = await getOrIframe(
        '/v2/drafts/' + did,
        API + '/v2/drafts/' + did,
        APP + '/draft/' + did
      );
      if (r.ok && r.data) {
        bulk['/v2/drafts/' + did] = r.data;
        draftsFetched++;
        if (r.source === 'cache' || r.source === 'pre-cache') cachedDraftCount++; else bgFetchedDraftCount++;
        if (r.data.draft && r.data.draft.slate_id) slateIds.add(r.data.draft.slate_id);
      }
      if ((i + 1) % CHECKPOINT_INTERVAL === 0 || i === allDraftIds.length - 1) {
        for (const sid of slateIds) await _fetchSlateMetadata(sid);
        const refresh = await udBulk(['/v1/slates/', '/v2/slates/', '/v2/drafts/']);
        Object.keys(refresh).forEach(p => { if (!bulk[p]) bulk[p] = refresh[p]; });
        publishCheckpoint(bulk, 'draft ' + (i + 1) + '/' + allDraftIds.length);
      }
      await new Promise(resolve => setTimeout(resolve, 200));
    }

    if (status) status.textContent = 'Fetching player metadata…';
    for (const sid of slateIds) {
      await _fetchSlateMetadata(sid);
    }

    // v0.10.11: iframe sweep for any slate whose /players still isn't in bulk.
    // Per-checkpoint _fetchSlateMetadata stays fast (mainfetch-only). This runs
    // once, here, to recover slates where mainfetch's circuit breaker tripped.
    // Without this recovery, drafts on those slates have unresolvable
    // appearance_ids → no picks → silently dropped in buildAggregatedFromBulk.
    const _missingPlayerSlates = [];
    for (const sid of slateIds) {
      if (!bulk['/v2/slates/' + sid + '/players'] && !bulk['/v1/slates/' + sid + '/players']) {
        _missingPlayerSlates.push(sid);
      }
    }
    if (_missingPlayerSlates.length) {
      console.log('[MFF/sync] iframe-sweep for', _missingPlayerSlates.length,
                  'slate(s) still missing /players:', _missingPlayerSlates);
      for (let i = 0; i < _missingPlayerSlates.length; i++) {
        const sid = _missingPlayerSlates[i];
        if (status) status.textContent = 'Recovering slate metadata ' + (i + 1) + '/' + _missingPlayerSlates.length + '…';
        const iframeUrl = APP + '/completed/' + sid + '/';
        let pr = await getOrIframe('/v2/slates/' + sid + '/players',
                                   _udUrl('/v2/slates/' + sid + '/players'),
                                   iframeUrl, 3000);
        if (pr.ok) {
          bulk['/v2/slates/' + sid + '/players'] = pr.data;
          console.log('[MFF/sync] ✓ iframe-recovered /v2 players for slate', sid);
        } else {
          pr = await getOrIframe('/v1/slates/' + sid + '/players',
                                 _udUrl('/v1/slates/' + sid + '/players'),
                                 iframeUrl, 3000);
          if (pr.ok) {
            bulk['/v1/slates/' + sid + '/players'] = pr.data;
            console.log('[MFF/sync] ✓ iframe-recovered /v1 players for slate', sid);
          } else {
            console.warn('[MFF/sync] ✗ iframe also failed for slate', sid,
                         '— drafts on this slate may drop from portfolio');
          }
        }
      }
    }

    // v0.10.14: noPicks recovery — page-snoop cache may have snapshotted
    // /v2/drafts/<id> while the draft was still in progress (no picks yet),
    // and the cache hit on this sync short-circuited the live fetch before
    // iframe fallback could run. Result: just-finalized drafts ship to the
    // portfolio without picks → silently dropped at the !Array.isArray(picks)
    // filter in buildAggregatedFromBulk. Detect these here and force a fresh
    // mainfetch (bypassing cache); iframe fallback if mainfetch fails.
    const _noPickDraftIds = [];
    for (const path of Object.keys(bulk)) {
      if (!path.startsWith('/v2/drafts/')) continue;
      const did = path.substring('/v2/drafts/'.length);
      if (!did || did.indexOf('/') !== -1) continue; // must be a single draft id
      const draft = bulk[path] && bulk[path].draft;
      if (draft && !Array.isArray(draft.picks)) _noPickDraftIds.push(did);
    }
    if (_noPickDraftIds.length) {
      console.log('[MFF/sync] refetching', _noPickDraftIds.length,
                  'stale-cache draft(s) with no picks:', _noPickDraftIds);
      for (let i = 0; i < _noPickDraftIds.length; i++) {
        const did = _noPickDraftIds[i];
        if (status) status.textContent = 'Refetching finalized draft ' + (i + 1) + '/' + _noPickDraftIds.length + '…';
        // Force fresh — mainfetch bypasses the page-snoop cache that getEndpoint hits first.
        let _gotPicks = false;
        const mf = await mainFetch(API + '/v2/drafts/' + did, 12000);
        if (mf.ok && mf.data && mf.data.draft && Array.isArray(mf.data.draft.picks)) {
          bulk['/v2/drafts/' + did] = mf.data;
          _gotPicks = true;
          console.log('[MFF/sync] ✓ mainfetch refetched picks for', did);
        }
        if (!_gotPicks) {
          // Iframe loads UD's own /draft/<id> page fresh — UD re-fetches and
          // injected.js snoops the new response into sessionStorage.
          const r = await visitInIframe(APP + '/draft/' + did, '/v2/drafts/' + did, 40000, 3000);
          if (r.ok) {
            const refreshed = await udBulk(['/v2/drafts/' + did]);
            const rd = refreshed['/v2/drafts/' + did];
            if (rd && rd.draft && Array.isArray(rd.draft.picks)) {
              bulk['/v2/drafts/' + did] = rd;
              _gotPicks = true;
              console.log('[MFF/sync] ✓ iframe refetched picks for', did);
            }
          }
        }
        if (!_gotPicks) {
          console.warn('[MFF/sync] ✗ refetch failed for', did, '— still no picks; UD may not have finalized this draft yet');
        }
      }
    }

    const final = await udBulk(['/v1/slates/', '/v2/slates/', '/v2/drafts/', '/v1/user/']);
    Object.keys(final).forEach(p => { if (!bulk[p]) bulk[p] = final[p]; });

    // v0.10.14: final publish after post-loop player metadata recovery and
    // noPicks refetch. Without this, drafts whose picks/players were rescued
    // post-loop never make it into the site portfolio — the last in-loop
    // checkpoint shipped before any of that recovery happened.
    if (_noPickDraftIds.length || _missingPlayerSlates.length) {
      try { publishCheckpoint(bulk, 'final-recovery'); } catch (e) { console.warn('[MFF/sync] final-recovery publish error:', e && e.message); }
    }

    const appearanceToPlayer = new Map();
    const playerById = new Map();
    const appearancePos = new Map();
    const appearanceProjTotal = new Map();
    const _VALID_POS = new Set(['QB', 'RB', 'WR', 'TE', 'K', 'DST', 'DEF', 'D/ST', 'FLEX']);
    function _normalizePos(v) {
      if (!v || typeof v !== 'string') return '';
      const s = v.toUpperCase().trim();
      if (_VALID_POS.has(s)) return s === 'DEF' || s === 'D/ST' ? 'DST' : s;
      const m = s.match(/^([A-Z]+)\d*$/);
      if (m && _VALID_POS.has(m[1])) return m[1];
      return '';
    }
    for (const path of Object.keys(bulk)) {
      const d = bulk[path];
      if (!d) continue;
      if (path.endsWith('/appearances') || path.includes('/scoring_types/')) {
        const arr = d.appearances || [];
        for (const a of arr) {
          if (a && a.id && a.player_id) appearanceToPlayer.set(a.id, a.player_id);
        }
      }
      if (path.endsWith('/players')) {
        const arr = d.players || [];
        for (const p of arr) {
          if (!p || !p.id) continue;
          const fullName = ((p.first_name || '') + ' ' + (p.last_name || '')).trim();
          const posVal = p.position_name || p.position || p.position_code ||
                         p.player_position || p.position_id || '';
          const teamVal = p.team_id || p.team || p.team_abbr || '';
          playerById.set(p.id, {
            name: fullName,
            pos: _normalizePos(posVal),
            team: teamVal
          });
        }
      }
    }
    console.log('[MFF/sync] resolved', appearanceToPlayer.size, 'appearances,', playerById.size, 'players');

    const aggregated = [];
    const aggregatedRaw = [];
    if (status) {
      const missing = totalDraftsExpected - draftsFetched;
      // v0.10.13: noPicks count surfaces drafts UD returned without a picks
      // array. Cause varies — could be a slow draft still in progress, a
      // just-completed draft whose roster UD hasn't finalized yet, or a
      // draft pending review. Either way the extension correctly skips them
      // (no roster to ingest yet) and they'll appear on the next sync once
      // UD's API returns full data.
      const noPicks = (window.__mffSyncDiag && Array.isArray(window.__mffSyncDiag.droppedNoPicks))
        ? window.__mffSyncDiag.droppedNoPicks.length : 0;
      const emitted = draftsFetched - noPicks;
      let msg = 'Synced ' + emitted + ' drafts';
      if (missing > 0) msg += ' (' + missing + ' couldn\'t be fetched)';
      if (noPicks > 0) msg += ' — ' + noPicks + ' not yet finalized on UD (will sync on retry)';
      status.textContent = msg;
    }
  }

  const PREMIUM_TTL_MS = 24 * 60 * 60 * 1000;

  function isCacheFresh(user) {
    if (!user || !user.syncedAt) return false;
    return (Date.now() - user.syncedAt) < PREMIUM_TTL_MS;
  }

  function applyPremiumGate(user) {
    state.user = user || null;
    const lockEl = document.getElementById('mff-lock');
    const lockStatus = document.getElementById('mff-lock-status');
    const lockMsg = document.getElementById('mff-lock-msg');
    const cacheFresh = isCacheFresh(user);
    const isPremium = !!(user && user.premium && cacheFresh);

    const hideWhenLocked = [
      'mff-setup', 'mff-tabs', 'mff-pick-line',
      'mff-roster-wrap', 'mff-recs-wrap', 'mff-projections-wrap', 'mff-settings-wrap'
    ];

    if (!isPremium) {
      if (lockEl) lockEl.style.display = '';
      hideWhenLocked.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.display = 'none';
      });
      if (lockMsg) lockMsg.textContent = 'Sign in at myfantasyfootball.co to unlock the draft helper.';
    } else {
      if (lockEl) lockEl.style.display = 'none';
      if (typeof enterDraftMode === 'function') enterDraftMode();
    }

    // v0.9.68: update Settings → Account row regardless of lock state.
    const acctStatus = document.getElementById('mff-acct-status');
    const acctEmail  = document.getElementById('mff-acct-email');
    const acctTier   = document.getElementById('mff-acct-tier');
    if (acctEmail && acctStatus && acctTier) {
      if (user && user.email) {
        acctStatus.textContent = '✓'; // ✓
        acctStatus.style.color = isPremium ? '#22c55e' : '#f59e0b';
        acctEmail.textContent = user.email;
        acctTier.textContent = isPremium ? 'PREMIUM' : 'FREE';
        acctTier.style.background = isPremium ? '#22c55e' : '#3a3d45';
        acctTier.style.color = isPremium ? '#0e0f12' : '#c8ccd4';
      } else {
        acctStatus.textContent = '✗'; // ✗
        acctStatus.style.color = '#ef4444';
        acctEmail.textContent = 'Not signed in';
        acctTier.textContent = '';
        acctTier.style.background = 'transparent';
      }
    }
  }

  let _draftModeEntered = false;
  function enterDraftMode() {
    if (_draftModeEntered) return;
    _draftModeEntered = true;
    const setupEl = document.getElementById('mff-setup');
    if (setupEl) setupEl.style.display = 'none';
    // v0.9.68: default to Rankings tab — show recs+pick-line, hide
    // roster widget (user toggles to Roster tab to see VOR analysis).
    ['mff-tabs', 'mff-pick-line', 'mff-recs-wrap'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.style.display = '';
    });
    const _rosterWrap = document.getElementById('mff-roster-wrap');
    if (_rosterWrap) _rosterWrap.style.display = 'none';
    if (typeof render === 'function') render();
  }
  function loadStoredUser(cb) {
    try {
      chrome.storage.local.get(['mff_user'], (res) => {
        const user = res && res.mff_user ? res.mff_user : null;
        applyPremiumGate(user);
        if (cb) cb(user);
      });
    } catch (e) {
      applyPremiumGate(null);
      if (cb) cb(null);
    }
  }

  setInterval(() => {
    try {
      chrome.storage.local.get(['mff_user'], (res) => {
        applyPremiumGate(res && res.mff_user ? res.mff_user : null);
      });
    } catch (_) {}
  }, 60 * 1000);

  function loadStoredPortfolio() {
    try {
      chrome.storage.local.get(["mff_portfolio", "mff_rankings", "mff_adp_history"], (res) => {
        // v0.9.99: hydrate ADP-movement history so the daily-snapshot data
        // written by the daily refresh path is visible to _computeAdpDelta.
        // Without this, state.adpHistory stayed [] forever and every ADP
        // movement lookup returned null even after multiple days of captures.
        if (res && Array.isArray(res.mff_adp_history)) {
          state.adpHistory = res.mff_adp_history;
          console.log('[MFF/adp] loaded history with', state.adpHistory.length, 'snapshot(s)');
        }
        if (res && res.mff_portfolio) {
          state.portfolio = res.mff_portfolio;
          if (typeof startExposureDecorator === 'function') startExposureDecorator();
        }
        if (res && res.mff_rankings && Array.isArray(res.mff_rankings.rankings)) {
          if (typeof applyRankings === 'function') applyRankings(res.mff_rankings.rankings, res.mff_rankings.irOut);
        }
        if (document.getElementById("mff-recs") && typeof render === 'function') render();
      });
      chrome.storage.onChanged.addListener((changes, area) => {
        if (area !== "local") return;
        let shouldRender = false;
        // Live-unlock: when the user signs in on the MFF site, the bridge writes
        // mff_user → re-run the premium gate so the Underdog sidebar drops the
        // lock screen without a page reload.
        if (changes.mff_user) {
          try { applyPremiumGate(changes.mff_user.newValue || null); } catch (_) {}
          // Newly premium → pull the live full boards now (the bundle only
          // carries the free top-36 slice; the boot-time fetch was skipped).
          try {
            const nu = changes.mff_user.newValue, was = changes.mff_user.oldValue;
            if (nu && nu.premium && !(was && was.premium) && typeof refreshJackBoards === 'function') refreshJackBoards();
          } catch (_) {}
        }
        if (changes.mff_portfolio && changes.mff_portfolio.newValue) {
          state.portfolio = changes.mff_portfolio.newValue;
          shouldRender = true;
        }
        if (changes.mff_rankings && changes.mff_rankings.newValue && Array.isArray(changes.mff_rankings.newValue.rankings)) {
          if (typeof applyRankings === "function") applyRankings(changes.mff_rankings.newValue.rankings, changes.mff_rankings.newValue.irOut);
          shouldRender = true;
        }
        // v0.9.99: live-pick up ADP history changes so a snapshot written by
        // the daily refresh appears in movement deltas without a page reload.
        if (changes.mff_adp_history && Array.isArray(changes.mff_adp_history.newValue)) {
          state.adpHistory = changes.mff_adp_history.newValue;
          shouldRender = true;
        }
        if (shouldRender && document.getElementById("mff-recs") && typeof render === "function") render();
      });
    } catch (e) {}
  }

  // v0.10.59: merge the site-hosted ADP history feed into local
  // mff_adp_history. The local list only gains a snapshot on days this
  // machine opened Underdog; the site feed is built EVERY morning by the
  // 9 AM consensus-ADP task (from the shared/ud_adp_latest Firestore
  // mirror), so merging fills the gaps and seeds fresh installs — keeping
  // the ▲▼ ADP-movement indicators honest over the full lookback window.
  // Local entries win on date collisions (they were captured live).
  function _mergeSiteAdpHistory() {
    try {
      chrome.runtime.sendMessage({ type: 'mff-adp-history-fetch' }, (res) => {
        if (chrome.runtime.lastError || !res || !res.ok || !res.data) return;
        const siteDays = Array.isArray(res.data.days) ? res.data.days : [];
        if (!siteDays.length) return;
        chrome.storage.local.get(['mff_adp_history'], (r2) => {
          const local = (r2 && Array.isArray(r2.mff_adp_history)) ? r2.mff_adp_history : [];
          const byDate = new Map();
          siteDays.forEach((d) => {
            if (d && d.date && d.adps) byDate.set(d.date, { date: d.date, adps: d.adps });
          });
          local.forEach((d) => { if (d && d.date) byDate.set(d.date, d); });
          const merged = Array.from(byDate.values())
            .sort((a, b) => (a.date || '').localeCompare(b.date || ''))
            .slice(-30);
          if (merged.length > local.length) {
            chrome.storage.local.set({ mff_adp_history: merged }, () => {
              console.log('[MFF/adp] merged site ADP history: ' + local.length +
                          ' local + ' + siteDays.length + ' site day(s) -> ' + merged.length);
            });
          }
        });
      });
    } catch (_) {}
  }

  function boot() {
    if (!document.body) { window.addEventListener("DOMContentLoaded", boot); return; }
    if (typeof loadPlayers !== "function") return;
    loadPlayers().then(function() {
      if (typeof injectSidebar === "function") injectSidebar();
      loadStoredUser();
      loadStoredPortfolio();
      refreshJackBoards(); // v0.15.1: non-blocking; baked/bridge boards work until it lands
      _mergeSiteAdpHistory();
      // v0.9.99: kick off the daily ADP-snapshot refresh so movement deltas
      // actually have data to compare against. This was defined but never
      // called, leaving mff_adp_history empty on every machine.
      if (typeof _dailyAdpRefreshIfNeeded === 'function') {
        // Defer so UD's slate XHRs have a chance to populate the cache first.
        setTimeout(function () {
          try { _dailyAdpRefreshIfNeeded(); } catch (e) { console.warn('[MFF/adp] daily refresh kickoff error:', e); }
        }, 5000);
      }
    }).catch(function(err) { try { console.error("[MFF] init failed:", err); } catch(_) {} });
  }

  boot();
})();
