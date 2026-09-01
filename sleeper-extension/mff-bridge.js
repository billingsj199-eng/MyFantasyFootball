/* MFF Sleeper Helper — mff-bridge.js (content script on myfantasyfootball.co)
 *
 * Persists the site's signed-in user + premium flag (dispatched by
 * mff-page-user.js in the MAIN world) into this extension's chrome.storage,
 * powering the sidebar's premium gate. Same contract as the Underdog helper.
 */
(function () {
  "use strict";
  if (window.__mffSleeperBridgeLoaded) return;
  window.__mffSleeperBridgeLoaded = true;

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
        boards: d.boards, tiers: d.tiers || {}, ir: d.ir || null,
        syncedAt: d.syncedAt || Date.now()
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
