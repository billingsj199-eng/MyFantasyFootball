/* MFF mff-bridge — minimal restored after corruption (v0.9.94+). */
(function () {
  "use strict";
  if (window.__mffBridgeLoaded) return;
  window.__mffBridgeLoaded = true;

  function safeSet(key, val) {
    try {
      if (!chrome || !chrome.runtime || !chrome.runtime.id) return;
      chrome.storage.local.set({ [key]: val }, function(){});
    } catch(_){}
  }
  function buildPortfolio(teams) {
    const counts = {}, pairs = {};
    const numTeams = teams.length;
    for (const team of teams) {
      const sorted = [...new Set(team)].sort();
      for (let i = 0; i < sorted.length; i++) {
        counts[sorted[i]] = (counts[sorted[i]] || 0) + 1;
        for (let j = i + 1; j < sorted.length; j++) {
          const k = sorted[i] + "|" + sorted[j];
          pairs[k] = (pairs[k] || 0) + 1;
        }
      }
    }
    const percent = {};
    for (const name in counts) percent[name] = (counts[name] / numTeams) * 100;
    return { teams, counts, pairs, percent, numTeams };
  }
  // v0.18.7: union of the site's portfolio (by draft id) and the extension's
  // own cumulative sync store. Before this, the site push and each extension
  // sync overwrote mff_portfolio with DIFFERENT scopes (site = everything,
  // sync = only drafts not already on the site), so the exposure % flipped
  // depending on which writer ran last.
  function unionTeams(siteDrafts, syncStore) {
    const byId = {};
    const noId = [];
    if (siteDrafts && siteDrafts.byId) {
      Object.keys(siteDrafts.byId).forEach(function (id) { byId[id] = siteDrafts.byId[id]; });
      (siteDrafts.noId || []).forEach(function (t) { noId.push(t); });
    }
    const syncDrafts = (syncStore && Array.isArray(syncStore.drafts)) ? syncStore.drafts : [];
    syncDrafts.forEach(function (d) {
      if (!d || !Array.isArray(d.picks)) return;
      const picks = d.picks.map(function (p) { return p && (p.name || p); }).filter(Boolean);
      if (!picks.length) return;
      if (d.id == null) { noId.push(picks); return; }
      if (!byId[String(d.id)]) byId[String(d.id)] = picks;   // site copy wins when both know it
    });
    return Object.keys(byId).map(function (id) { return byId[id]; }).concat(noId);
  }
  document.addEventListener("mff-portfolio-update", function (e) {
    try {
      const teams = e.detail && e.detail.teams;
      if (!Array.isArray(teams) || !teams.length) return;
      const syncedAt = (e.detail && e.detail.syncedAt) || Date.now();
      const drafts = e.detail && Array.isArray(e.detail.drafts) ? e.detail.drafts : null;
      if (!drafts) {
        // legacy shape (no ids) — old behaviour
        const p = buildPortfolio(teams);
        p.syncedAt = syncedAt;
        safeSet("mff_portfolio", p);
        return;
      }
      const incoming = { byId: {}, noId: [] };
      drafts.forEach(function (d) {
        if (!d || !Array.isArray(d.picks) || !d.picks.length) return;
        if (d.id != null) incoming.byId[String(d.id)] = d.picks; else incoming.noId.push(d.picks);
      });
      if (!chrome || !chrome.runtime || !chrome.runtime.id) return;
      // v0.18.11: MERGE into the stored site copy by draft id — never replace
      // it. The site's _mffSetPortfolio can momentarily expose a SHORT
      // portfolio (the extension's own few drafts, before the cloud load
      // merges in the rest); replacing the 286-draft copy with that 6-draft
      // snapshot was what dragged the exposure denominator back to 6.
      // Completed drafts are immutable, so keeping every id ever seen is safe;
      // the incoming roster wins for an id both know (fresher picks).
      chrome.storage.local.get(["mff_portfolio_sync", "mff_site_drafts"], function (res) {
        try {
          const prev = (res && res.mff_site_drafts) || {};
          const siteDrafts = { byId: {}, noId: [], syncedAt: syncedAt };
          if (prev.byId) Object.keys(prev.byId).forEach(function (id) { siteDrafts.byId[id] = prev.byId[id]; });
          Object.keys(incoming.byId).forEach(function (id) { siteDrafts.byId[id] = incoming.byId[id]; });
          // no-id rosters can't be de-duped by id; keep the larger set only
          siteDrafts.noId = (incoming.noId.length >= ((prev.noId && prev.noId.length) || 0)) ? incoming.noId : prev.noId;
          siteDrafts.lastPushCount = Object.keys(incoming.byId).length + incoming.noId.length;
          safeSet("mff_site_drafts", siteDrafts);
          const all = unionTeams(siteDrafts, res && res.mff_portfolio_sync);
          const p = buildPortfolio(all.length ? all : teams);
          p.syncedAt = syncedAt;
          p.numSite = Object.keys(siteDrafts.byId).length + siteDrafts.noId.length;
          p.numSitePush = siteDrafts.lastPushCount;
          p.source = "site+sync";
          safeSet("mff_portfolio", p);
        } catch(_){}
      });
    } catch(_){}
  });
  document.addEventListener("mff-rankings-update", function (e) {
    try {
      const rankings = e.detail && e.detail.rankings;
      if (!Array.isArray(rankings) || !rankings.length) return;
      const irOut = (e.detail && Array.isArray(e.detail.irOut)) ? e.detail.irOut : [];
      safeSet("mff_rankings", { rankings: rankings, irOut: irOut, syncedAt: (e.detail && e.detail.syncedAt) || Date.now() });
    } catch(_){}
  });
  document.addEventListener("mff-user-update", function (e) {
    try {
      const user = e.detail && e.detail.user;
      const payload = user ? Object.assign({}, user, { syncedAt: (e.detail && e.detail.syncedAt) || Date.now() }) : null;
      safeSet("mff_user", payload);
    } catch(_){}
  });
  document.addEventListener("mff-existing-draft-ids", function (e) {
    try {
      const ids = e.detail && e.detail.ids;
      if (!Array.isArray(ids)) return;
      safeSet("mff_existing_draft_ids", ids);
      safeSet("mff_existing_draft_ids_at", (e.detail && e.detail.syncedAt) || Date.now());
    } catch(_){}
  });
  document.addEventListener("mff-set-player-adps", function (e) {
    try {
      const detail = e.detail || {};
      if (!detail.adps) return;
      safeSet("mff_player_adps_snapshot", detail);
    } catch(_){}
  });
  document.addEventListener("mff-clear-extension-cache", function () {
    try {
      if (!chrome || !chrome.runtime || !chrome.runtime.id) return;
      chrome.storage.local.remove(["mff_portfolio_sync","mff_player_adps_snapshot","mff_existing_draft_ids","mff_existing_draft_ids_at","mff_portfolio","mff_site_drafts"], function(){});
    } catch(_){}
  });

  // Push synced portfolio back to MFF site (mff_portfolio_sync → page event)
  function pushSitePortfolio(p) {
    if (!p) return;
    try {
      document.dispatchEvent(new CustomEvent("mff-portfolio-from-extension", {
        detail: { portfolio: p, syncedAt: p.syncedAt || Date.now() }
      }));
    } catch(_){}
  }
  function pushAdpSnapshot(s) {
    if (!s || !s.adps) return;
    try {
      document.dispatchEvent(new CustomEvent("mff-set-player-adps", { detail: s }));
    } catch(_){}
  }

  // === ADP HISTORY BACKUP BRIDGE ===
  // Pushes daily ADP snapshots captured by the extension up to MFF site (which
  // mirrors them in Firestore). Pulls history back down on MFF site boot so a
  // chrome.storage wipe is recoverable. Suppress flag prevents the pull→write→
  // push echo loop: when we write to chrome.storage as part of recovery, skip
  // dispatching mff-save-adp-history for that one change event.
  var _suppressNextHistorySave = false;
  var _historyFetched = false;
  var _historyRetryCount = 0;
  var MAX_FETCH_RETRIES = 3; // 3 × 10s = 30s, enough for auth to settle (B1 short-circuits permission-denied on the site side)

  function pushAdpHistory(history) {
    if (!Array.isArray(history) || !history.length) return;
    try {
      document.dispatchEvent(new CustomEvent("mff-save-adp-history", {
        detail: { history: history }
      }));
    } catch(_){}
  }

  function requestAdpHistoryRecovery() {
    if (_historyFetched) return;
    if (_historyRetryCount++ >= MAX_FETCH_RETRIES) return;
    try {
      document.dispatchEvent(new CustomEvent("mff-fetch-adp-history"));
    } catch(_){}
  }

  document.addEventListener("mff-adp-history-fetched", function (e) {
    try {
      var remote = e.detail && e.detail.history;
      if (!Array.isArray(remote) || !remote.length) return;
      _historyFetched = true;
      chrome.storage.local.get(["mff_adp_history"], function (res) {
        var local = Array.isArray(res && res.mff_adp_history) ? res.mff_adp_history : [];
        // Union by date — latest capturedAt wins
        var byDate = new Map();
        var sources = [remote, local];
        for (var si = 0; si < sources.length; si++) {
          var arr = sources[si];
          for (var i = 0; i < arr.length; i++) {
            var s = arr[i];
            if (!s || !s.date) continue;
            var existing = byDate.get(s.date);
            if (!existing || (s.capturedAt || 0) > (existing.capturedAt || 0)) {
              byDate.set(s.date, s);
            }
          }
        }
        var merged = Array.from(byDate.values()).sort(function (a, b) {
          return (a.date || "").localeCompare(b.date || "");
        });
        // Skip write if same date set in same order (no new info)
        var same = local.length === merged.length &&
                   local.every(function (s, i) { return s && merged[i] && s.date === merged[i].date; });
        if (same) return;
        _suppressNextHistorySave = true;
        chrome.storage.local.set({ mff_adp_history: merged }, function () {
          console.log("[MFF/adp-backup] merged Firestore→local: " + merged.length + " snapshot(s), dates: " + merged.map(function(s){return s.date;}).join(","));
        });
      });
    } catch(_){}
  });

  try {
    chrome.storage.local.get(["mff_portfolio_sync","mff_player_adps_snapshot"], function (res) {
      if (res && res.mff_portfolio_sync) pushSitePortfolio(res.mff_portfolio_sync);
      if (res && res.mff_player_adps_snapshot) pushAdpSnapshot(res.mff_player_adps_snapshot);
    });
    chrome.storage.onChanged.addListener(function (changes, area) {
      if (area !== "local") return;
      if (changes.mff_portfolio_sync && changes.mff_portfolio_sync.newValue) pushSitePortfolio(changes.mff_portfolio_sync.newValue);
      if (changes.mff_player_adps_snapshot && changes.mff_player_adps_snapshot.newValue) pushAdpSnapshot(changes.mff_player_adps_snapshot.newValue);
      if (changes.mff_adp_history && changes.mff_adp_history.newValue) {
        if (_suppressNextHistorySave) { _suppressNextHistorySave = false; return; }
        pushAdpHistory(changes.mff_adp_history.newValue);
      }
    });
    // Kick off initial recovery request + retry until page-bridge responds
    // (page-bridge no-ops while auth isn't ready; the retry handles that gap).
    requestAdpHistoryRecovery();
    setInterval(requestAdpHistoryRecovery, 10000);
  } catch(_){}
})();
