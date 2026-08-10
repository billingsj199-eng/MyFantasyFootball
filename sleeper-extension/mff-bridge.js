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
})();
