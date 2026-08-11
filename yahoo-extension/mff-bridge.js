/* MFF Yahoo League Import — mff-bridge.js (content script on myfantasyfootball.co)
 *
 * Courier between chrome.storage.local (written by yahoo-export.js on
 * football.fantasysports.yahoo.com) and the MFF page. Pushes every stored
 * league via the "mff-yahoo-league-from-extension" CustomEvent — once on
 * load and again whenever the store changes. Same contract as the ESPN
 * helper's bridge; payload shape lives in yahoo-normalize.js.
 */
(function () {
  "use strict";
  if (window.__mffYahooBridgeLoaded) return;
  window.__mffYahooBridgeLoaded = true;

  function push(leagues) {
    if (!leagues || !Object.keys(leagues).length) return;
    try {
      document.dispatchEvent(new CustomEvent("mff-yahoo-league-from-extension", {
        detail: { leagues: leagues, pushedAt: Date.now() }
      }));
    } catch (_) {}
  }

  try {
    chrome.storage.local.get(["mff_yahoo_leagues"], function (res) {
      if (res && res.mff_yahoo_leagues) push(res.mff_yahoo_leagues);
    });
    chrome.storage.onChanged.addListener(function (changes, area) {
      if (area !== "local") return;
      if (changes.mff_yahoo_leagues && changes.mff_yahoo_leagues.newValue) {
        push(changes.mff_yahoo_leagues.newValue);
      }
    });
  } catch (_) {}

  // Premium gate: persist the site's signed-in user + premium flag, dispatched
  // by mff-page-user.js (MAIN world). null on sign-out relocks the helper.
  document.addEventListener("mff-user-update", function (e) {
    try {
      var d = e.detail || {};
      var u = d.user;
      chrome.storage.local.set({ mff_user: u ? {
        uid: u.uid || null, email: u.email || null, premium: !!u.premium,
        syncedAt: d.syncedAt || Date.now()
      } : null });
    } catch (_) {}
  });

  // MY RANKS: persist the user's own site boards for the rec engine.

  // JACKS BOARDS (board-gating Phase B): persist Jack's full boards + tiers
  // shipped by a premium session — the sidebar's premium path once the direct
  // Firestore read is rules-gated (Phase C).
  document.addEventListener("mff-jacks-boards-update", function (e) {
    try {
      var d = e.detail || {};
      if (!d.boards) return;
      chrome.storage.local.set({ mff_jacks_boards: {
        boards: d.boards, tiers: d.tiers || {}, syncedAt: d.syncedAt || Date.now()
      } });
    } catch (_) {}
  });

  document.addEventListener("mff-my-rankings-update", function (e) {
    try {
      var d = e.detail || {};
      if (!d.boards) return;
      chrome.storage.local.set({ mff_my_rankings: { boards: d.boards, syncedAt: d.syncedAt || Date.now() } });
    } catch (_) {}
  });
})();
