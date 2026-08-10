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
  document.addEventListener("mff-portfolio-update", function (e) {
    try {
      const teams = e.detail && e.detail.teams;
      if (!Array.isArray(teams) || !teams.length) return;
      const p = buildPortfolio(teams);
      p.syncedAt = (e.detail && e.detail.syncedAt) || Date.now();
      safeSet("mff_portfolio", p);
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
      chrome.storage.local.remove(["mff_portfolio_sync","mff_player_adps_snapshot","mff_existing_draft_ids","mff_existing_draft_ids_at","mff_portfolio"], function(){});
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
