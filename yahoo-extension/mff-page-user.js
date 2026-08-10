/* MFF page-user bridge — runs in the MAIN world on myfantasyfootball.co.
 * Reads the signed-in Firebase user + premium flag (same probe order as the
 * Underdog helper's page-bridge.js) and dispatches 'mff-user-update' events
 * for the isolated-world mff-bridge.js to persist into this extension's
 * chrome.storage. Powers the premium gate in the sidebar.
 */
(function () {
  "use strict";
  if (window.__mffPageUserLoaded) return;
  window.__mffPageUserLoaded = true;
  function readUser() {
    try {
      if (window._mffUser && typeof window._mffUser === "object") {
        var u = window._mffUser;
        return { uid: u.uid || null, email: u.email || null, premium: !!u.premium };
      }
    } catch (_) {}
    try {
      if (window.firebase && window.firebase.apps && window.firebase.apps.length &&
          typeof window.firebase.auth === "function") {
        var fu = window.firebase.auth().currentUser;
        if (fu && fu.uid) {
          var prem = false;
          try { if (typeof window.checkPremiumStatus === "function" && window.checkPremiumStatus()) prem = true; } catch (_) {}
          try { if (typeof window.hasPremium === "function" && window.hasPremium()) prem = true; } catch (_) {}
          try { if (typeof window.isAdmin === "function" && window.isAdmin()) prem = true; } catch (_) {}
          return { uid: fu.uid, email: fu.email || null, premium: prem };
        }
      }
    } catch (_) {}
    return null;
  }
  var last = "";
  function tick() {
    try {
      var u = readUser();
      var h = u ? (u.uid + "|" + u.premium + "|" + u.email) : "null";
      if (h === last) return;
      last = h;
      document.dispatchEvent(new CustomEvent("mff-user-update", {
        detail: { user: u, syncedAt: Date.now() }
      }));
    } catch (_) {}
  }
  setInterval(tick, 3000);
  setTimeout(tick, 1500);
  setTimeout(tick, 5000);
})();
