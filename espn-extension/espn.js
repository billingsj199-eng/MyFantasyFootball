/* MFF ESPN League Import — espn.js (content script on fantasy.espn.com)
 *
 * Runs on any fantasy.espn.com/football/* page. When the URL carries a
 * leagueId, shows a small floating "Export to MFF" button. Clicking it
 * fetches the league from ESPN's own v3 API *from inside the user's
 * logged-in session* (credentials: include → espn_s2 + SWID ride along
 * automatically, private leagues included — no cookie pasting), normalizes
 * it (normalize.js), and stores it in chrome.storage.local. The
 * mff-bridge.js content script on myfantasyfootball.co picks it up from
 * there and hands it to the site.
 */
(function () {
  "use strict";
  if (window.__mffEspnLoaded) return;
  window.__mffEspnLoaded = true;

  var API = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/";
  // mDraftDetail rides along (credentialed, so private leagues included) —
  // normalize.js turns it into the payload's `draft` block for the MFF
  // My Teams draft board.
  var VIEWS = "?view=mTeam&view=mRoster&view=mSettings&view=mDraftDetail";

  function leagueIdFromUrl() {
    try {
      var m = new URLSearchParams(location.search).get("leagueId");
      return m && /^\d+$/.test(m) ? m : null;
    } catch (_) { return null; }
  }

  function seasonFromUrl() {
    try {
      var s = new URLSearchParams(location.search).get("seasonId");
      if (s && /^\d{4}$/.test(s)) return s;
    } catch (_) {}
    // Fantasy seasons run Aug-Jan; before August the upcoming season is the
    // current calendar year, in Jan-Feb the just-finished one is year - 1.
    var now = new Date();
    return String(now.getMonth() < 2 ? now.getFullYear() - 1 : now.getFullYear());
  }

  // SWID is a plain (non-HttpOnly) cookie on .espn.com — readable from the
  // content script. It equals the member id in the league payload, which is
  // how we auto-flag which team is the user's.
  function readSwid() {
    try {
      var m = document.cookie.match(/(?:^|;\s*)SWID=("?)([^;"]+)\1/);
      return m ? decodeURIComponent(m[2]) : null;
    } catch (_) { return null; }
  }

  function fetchLeague(leagueId, season) {
    return fetch(API + season + "/segments/0/leagues/" + leagueId + VIEWS, {
      credentials: "include",
      headers: { Accept: "application/json" }
    }).then(function (r) {
      if (!r.ok) throw new Error("ESPN API " + r.status + (r.status === 401 ? " (not logged in?)" : ""));
      return r.json();
    });
  }

  function saveLeague(payload) {
    return new Promise(function (res, rej) {
      try {
        if (!chrome || !chrome.runtime || !chrome.runtime.id) return rej(new Error("extension context gone"));
        payload.syncedAt = Date.now();
        chrome.storage.local.get(["mff_espn_leagues"], function (cur) {
          var all = (cur && cur.mff_espn_leagues) || {};
          all[payload.leagueId] = payload;
          chrome.storage.local.set({ mff_espn_leagues: all }, function () { res(); });
        });
      } catch (e) { rej(e); }
    });
  }

  // ── Floating export button ──────────────────────────────────────────
  var btn = null;
  function setBtn(text, disabled) { if (btn) { btn.textContent = text; btn.disabled = !!disabled; } }

  function onExport() {
    var leagueId = leagueIdFromUrl();
    if (!leagueId) return;
    setBtn("Exporting…", true);
    fetchLeague(leagueId, seasonFromUrl())
      .then(function (raw) {
        var norm = window.MFF_ESPN.normalizeEspnLeague(raw, readSwid());
        if (!norm) throw new Error("unexpected league payload");
        return saveLeague(norm).then(function () { return norm; });
      })
      .then(function (norm) {
        setBtn("✓ Saved " + norm.teamCount + " teams — open myfantasyfootball.co", false);
        setTimeout(function () { setBtn("Export league to MFF", false); }, 6000);
      })
      .catch(function (e) {
        console.warn("[MFF/espn] export failed:", e);
        setBtn("✗ " + e.message, false);
        setTimeout(function () { setBtn("Export league to MFF", false); }, 6000);
      });
  }

  function mount() {
    if (btn || !leagueIdFromUrl()) return;
    btn = document.createElement("button");
    btn.id = "mffEspnExportBtn";
    btn.textContent = "Export league to MFF";
    // Bottom-LEFT, stacked above the draft-probe pill (bottom:14px, left:14px)
    // — ESPN's Fantasy Chat panel owns the bottom-right corner and was
    // covering the button (Jack 2026-08-31).
    btn.style.cssText = [
      "position:fixed", "bottom:56px", "left:14px", "z-index:99999",
      "padding:10px 16px", "border-radius:8px", "border:1px solid #fbbf24",
      "background:#111827", "color:#fbbf24", "font:600 13px/1.2 system-ui,sans-serif",
      "cursor:pointer", "box-shadow:0 4px 14px rgba(0,0,0,.4)"
    ].join(";");
    btn.addEventListener("click", onExport);
    document.body.appendChild(btn);
  }

  // ESPN is a SPA — the leagueId can appear after client-side navigation.
  mount();
  var lastHref = location.href;
  setInterval(function () {
    if (location.href !== lastHref) {
      lastHref = location.href;
      if (!leagueIdFromUrl() && btn) { btn.remove(); btn = null; }
      mount();
    }
  }, 1000);
})();
