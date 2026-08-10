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
})();
