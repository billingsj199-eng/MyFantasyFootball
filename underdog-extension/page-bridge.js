/* MFF page-bridge — minimal restored after corruption (v0.9.94+).
 * Runs in MAIN world on myfantasyfootball.co (and legacy .org). Reads window._udPortfolio
 * + window.D + firebase user, dispatches to ISOLATED mff-bridge.
 */
(function () {
  "use strict";
  if (window.__mffPageBridgeLoaded) return;
  window.__mffPageBridgeLoaded = true;

  function teamsHash(teams) {
    if (!teams) return "";
    return teams.map(function(t){ return [].concat(t).sort().join(","); }).sort().join("|");
  }
  function extractTeams(src) {
    if (!src) return null;
    if (Array.isArray(src)) return null;
    if (src.drafts && typeof src.drafts === "object" && !Array.isArray(src.drafts)) {
      const teams = Object.values(src.drafts).map(function(d){
        if (Array.isArray(d.picks)) return d.picks.map(function(p){ return p && (p.name || p); }).filter(Boolean);
        return [];
      }).filter(function(t){ return t.length > 0; });
      return teams.length ? teams : null;
    }
    if (Array.isArray(src.drafts)) {
      const teams = src.drafts.map(function(d){
        if (Array.isArray(d.picks)) return d.picks.map(function(p){ return p && (p.name || p); }).filter(Boolean);
        return [];
      }).filter(function(t){ return t.length > 0; });
      return teams.length ? teams : null;
    }
    return null;
  }

  let lastPortHash = "";
  function tickPortfolio() {
    try {
      const teams = extractTeams(window._udPortfolio || window.udPortfolio || null);
      if (!teams) return;
      const h = teamsHash(teams);
      if (h === lastPortHash) return;
      lastPortHash = h;
      document.dispatchEvent(new CustomEvent("mff-portfolio-update", { detail: { teams: teams, syncedAt: Date.now() } }));
    } catch(_){}
  }

  // OUT FOR SEASON (IR) flag — same hide the site's season boards apply.
  // window._irIsOut lives in app.js; flagged players are skipped from rank
  // numbering (ranks compress, matching the visible board) and reported to
  // the extension via irOut so the sidebar can hide them too.
  function _irOut(name) {
    try { return typeof window._irIsOut === "function" && !!window._irIsOut(name); } catch(_) { return false; }
  }

  function buildRankMapFromBoard(boardArr, D) {
    if (!Array.isArray(boardArr) || !boardArr.length) return null;
    const map = new Map();
    let rank = 0;
    for (let i = 0; i < boardArr.length; i++) {
      const idx = boardArr[i];
      const d = D[idx];
      if (!d || !d.n || d._retired) continue;
      if (d.s === "K" || d.s === "DST") continue;
      if (!d.t || d.t === "TBD") continue;
      if (_irOut(d.n)) continue;
      rank++;
      map.set(d.n, rank);
    }
    return map.size ? map : null;
  }
  function extractRankings() {
    const D = window.D;
    if (!Array.isArray(D) || !D.length) return null;
    // PREMIUM (v0.17.2): Jack's boards only ship to a premium session — the
    // bundled players.json carries just the free top-36 slice, and this bridge
    // must not become the free path around that. The user's own "MY RANKS"
    // fallback still ships for everyone, but ONLY when the format was actually
    // customized: a virgin mine board is a live mirror of Jack's (site seeding
    // 2026-08-10), so shipping it would be the same leak with extra steps.
    const gu = readUser();
    const prem = !!(gu && gu.premium);
    const mineCustom = function (k) {
      try { return !!(window._mineIsCustom && window._mineIsCustom(k)); } catch (_) { return false; }
    };
    let bbMap = null, sfMap = null;
    try {
      const vb = window.versionBoards;
      if (prem && vb && vb.jacks) {
        bbMap = buildRankMapFromBoard(vb.jacks.bestball, D);
        sfMap = buildRankMapFromBoard(vb.jacks.superflex, D);
      }
      if (!bbMap && vb && vb.mine && (prem || mineCustom('bestball'))) {
        bbMap = buildRankMapFromBoard(vb.mine.bestball, D);
      }
      if (!sfMap && vb && vb.mine && (prem || mineCustom('superflex'))) {
        sfMap = buildRankMapFromBoard(vb.mine.superflex, D);
      }
    } catch(_){}
    // Free session with no custom boards: ship nothing — the d.myRank
    // fallback below is Jack's baked board order, same leak by another door.
    if (!prem && !bbMap && !sfMap) return null;
    const rows = [];
    const irOut = [];
    for (let i = 0; i < D.length; i++) {
      const d = D[i];
      if (!d || !d.n || !d.s || d._retired) continue;
      if (d.s === "K" || d.s === "DST") continue;
      if (!d.t || d.t === "TBD") continue;
      if (_irOut(d.n)) { irOut.push(d.n); continue; }
      const rank = (bbMap && bbMap.get(d.n)) || d.myRank || (i + 1);
      const mineSfRank = (sfMap && sfMap.get(d.n)) || null;
      rows.push({ n: d.n, s: d.s, t: d.t, myRank: rank, sfa: (d.sfa != null ? d.sfa : null), mineSfRank: mineSfRank });
    }
    if (!rows.length) return null;
    rows.sort(function(a,b){ return a.myRank - b.myRank; });
    for (let j = 0; j < rows.length; j++) rows[j].myRank = j + 1;
    return { rows: rows, irOut: irOut };
  }
  function rankingsHash(rows, irOut) {
    const parts = new Array(rows.length);
    for (let i = 0; i < rows.length; i++) {
      const r = rows[i];
      parts[i] = (r.n||"") + ":" + (r.myRank||0) + (r.sfa != null ? ("@"+r.sfa) : "");
    }
    return parts.join("|") + "|len:" + rows.length + "|ir:" + (irOut || []).join(",");
  }
  let lastRankHash = "";
  function tickRankings() {
    try {
      const res = extractRankings();
      if (!res) return;
      const h = rankingsHash(res.rows, res.irOut);
      if (h === lastRankHash) return;
      lastRankHash = h;
      document.dispatchEvent(new CustomEvent("mff-rankings-update", { detail: { rankings: res.rows, irOut: res.irOut, syncedAt: Date.now() } }));
    } catch(_){}
  }

  function readUser() {
    try {
      if (window._mffUser && typeof window._mffUser === "object") {
        const u = window._mffUser;
        return { uid: u.uid || null, email: u.email || null, premium: !!u.premium };
      }
    } catch(_){}
    try {
      if (window.firebase && typeof window.firebase.auth === "function") {
        const fu = window.firebase.auth().currentUser;
        if (fu && fu.uid) {
          let prem = false;
          try { if (typeof window.checkPremiumStatus === "function" && window.checkPremiumStatus()) prem = true; } catch(_){}
          try { if (typeof window.hasPremium === "function" && window.hasPremium()) prem = true; } catch(_){}
          try { if (typeof window.isAdmin === "function" && window.isAdmin()) prem = true; } catch(_){}
          return { uid: fu.uid, email: fu.email || null, premium: prem };
        }
      }
    } catch(_){}
    return null;
  }
  let lastUserHash = "";
  function tickUser() {
    try {
      const u = readUser();
      const h = u ? (u.uid + "|" + u.premium + "|" + u.email) : "null";
      if (h === lastUserHash) return;
      lastUserHash = h;
      document.dispatchEvent(new CustomEvent("mff-user-update", { detail: { user: u, syncedAt: Date.now() } }));
    } catch(_){}
  }

  let lastIdsHash = "";
  // A best-ball draft is 18 rounds; if a draft was synced mid-draft (picks < 18),
  // exclude it from the skip-list so the next sync re-fetches it. Otherwise
  // partial-pick drafts get permanently stuck at their first-fetch state.
  function _draftIsComplete(d) {
    if (!d) return false;
    const myPicks = Array.isArray(d.picks) ? d.picks.length : 0;
    if (myPicks >= 18) return true;
    const at = d.allTeams && typeof d.allTeams === "object" ? d.allTeams : null;
    if (!at) return false;
    const size = d.size || 12;
    const entries = Object.values(at);
    if (entries.length < size) return false;
    return entries.every(function(t){ return (t && t.pickCount >= 18); });
  }
  function tickExistingDraftIds() {
    try {
      const p = window._udPortfolio;
      if (!p || !p.drafts) return;
      const drafts = Array.isArray(p.drafts) ? p.drafts : Object.values(p.drafts);
      const ids = [];
      for (const d of drafts) {
        if (!d || !d.id) continue;
        if (_draftIsComplete(d)) ids.push(d.id);
      }
      const hash = ids.length + ":" + ids.slice(0, 5).join(",");
      if (hash === lastIdsHash) return;
      lastIdsHash = hash;
      document.dispatchEvent(new CustomEvent("mff-existing-draft-ids", { detail: { ids: ids, syncedAt: Date.now() } }));
    } catch(_){}
  }

  // Listen for portfolio coming back FROM extension into MFF site
  document.addEventListener("mff-portfolio-from-extension", function (e) {
    try {
      const p = e.detail && e.detail.portfolio;
      if (!p) return;
      if (typeof window._mffSetPortfolio === "function") window._mffSetPortfolio(p);
    } catch(_){}
  });
  document.addEventListener("mff-set-player-adps", function (e) {
    try {
      const detail = e.detail || {};
      if (!detail.adps) return;
      if (typeof window._mffSetAdpSnapshot === "function") window._mffSetAdpSnapshot(detail);
      else window.__mffPendingAdpSnapshot = detail;
    } catch(_){}
  });

  // ADP HISTORY BACKUP — push to Firestore when extension captures a new snapshot
  document.addEventListener("mff-save-adp-history", function (e) {
    try {
      const history = e.detail && e.detail.history;
      if (!Array.isArray(history) || !history.length) return;
      if (typeof window._mffSaveAdpHistory === "function") window._mffSaveAdpHistory(history);
    } catch(_){}
  });
  // ADP HISTORY BACKUP — pull from Firestore when extension requests recovery.
  // mff-bridge dispatches this on its boot. We wait until auth resolves before
  // attempting the fetch (auth callbacks set window._authCurrentUser); if it's
  // not ready yet, queue and retry on each fire.
  document.addEventListener("mff-fetch-adp-history", function () {
    try {
      if (typeof window._mffLoadAdpHistory !== "function") return;
      window._mffLoadAdpHistory().then(function (history) {
        if (!Array.isArray(history) || !history.length) return;
        document.dispatchEvent(new CustomEvent("mff-adp-history-fetched", {
          detail: { history: history, fetchedAt: Date.now() }
        }));
      }).catch(function(_){});
    } catch(_){}
  });

  function tickAll() { tickPortfolio(); tickRankings(); tickUser(); tickExistingDraftIds(); }
  setInterval(tickAll, 3000);
  setTimeout(tickAll, 1500);
  setTimeout(tickAll, 5000);

  // Hash-based My Teams jump (post-sync deep link)
  function maybeJumpToMyTeams() {
    if ((location.hash || "").toLowerCase() !== "#mff-myteams") return;
    let tries = 0;
    const iv = setInterval(function () {
      const btn = document.getElementById("navMyTeamsBtn");
      if (btn) {
        btn.click();
        try { if (typeof window._mtSwitchSource === "function") window._mtSwitchSource("underdog"); } catch(_){}
        clearInterval(iv);
        try { history.replaceState(null, "", location.pathname + location.search); } catch(_){}
      } else if (++tries > 30) clearInterval(iv);
    }, 250);
  }
  maybeJumpToMyTeams();
  window.addEventListener("hashchange", maybeJumpToMyTeams);
})();
