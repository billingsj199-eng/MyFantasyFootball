/* MFF Yahoo League Import — yahoo-export.js (content script on
 * football.fantasysports.yahoo.com)
 *
 * Yahoo has no cookie-auth JSON API, but its league pages are
 * server-rendered — so the exporter fetches each page same-origin (session
 * cookies ride along automatically), parses with DOMParser, and normalizes
 * via yahoo-normalize.js:
 *   /f1/<id>            → standings (teams, records, my-team nav link)
 *   /f1/<id>/<teamId>   → every team's roster (one fetch per team, throttled)
 * Result stored in chrome.storage `mff_yahoo_leagues`; mff-bridge.js hands
 * it to myfantasyfootball.co (same flow as the ESPN helper).
 */
(function () {
  "use strict";
  if (window.__mffYahooExportLoaded) return;
  window.__mffYahooExportLoaded = true;

  function leagueIdFromUrl() {
    var m = location.pathname.match(/\/f1\/(\d+)/);
    return m ? m[1] : null;
  }

  function fetchDoc(path) {
    return fetch(path, { credentials: "include" }).then(function (r) {
      if (!r.ok) throw new Error("Yahoo " + r.status + " on " + path);
      return r.text();
    }).then(function (html) {
      return new DOMParser().parseFromString(html, "text/html");
    });
  }

  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  function getScoringPrefs(leagueId) {
    return new Promise(function (res) {
      try {
        chrome.storage.local.get(["yahooLeague_" + leagueId], function (cur) {
          var lg = cur && cur["yahooLeague_" + leagueId];
          res((lg && lg.scoringPrefs) || null);
        });
      } catch (_) { res(null); }
    });
  }

  function saveLeague(payload) {
    return new Promise(function (res, rej) {
      try {
        if (!chrome || !chrome.runtime || !chrome.runtime.id) return rej(new Error("extension context gone"));
        payload.syncedAt = Date.now();
        chrome.storage.local.get(["mff_yahoo_leagues"], function (cur) {
          var all = (cur && cur.mff_yahoo_leagues) || {};
          all[payload.leagueId] = payload;
          chrome.storage.local.set({ mff_yahoo_leagues: all }, function () { res(); });
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
    setBtn("Reading league…", true);
    var N = window.MFF_YAHOO;
    var standings = null;

    fetchDoc("/f1/" + leagueId)
      .then(function (doc) {
        standings = N.parseStandingsDoc(doc, leagueId);
        if (!standings.teams.length) {
          // Some league skins keep standings off the home page.
          return fetchDoc("/f1/" + leagueId + "/standings").then(function (d2) {
            var s2 = N.parseStandingsDoc(d2, leagueId);
            if (s2.teams.length) standings = s2;
          });
        }
      })
      .then(function () {
        if (!standings.teams.length) throw new Error("no teams found — open your league home page and retry");
        var i = 0;
        function next() {
          if (i >= standings.teams.length) return Promise.resolve();
          var t = standings.teams[i++];
          setBtn("Exporting… " + i + "/" + standings.teams.length, true);
          return fetchDoc("/f1/" + leagueId + "/" + t.teamId).then(function (doc) {
            var parsed = N.parseTeamDoc(doc);
            t.roster = parsed ? parsed.roster : [];
            t.slots = parsed ? parsed.slots : [];
          }).catch(function () { t.roster = []; t.slots = []; })
            .then(function () { return sleep(350); }).then(next);
        }
        return next();
      })
      .then(function () { return getScoringPrefs(leagueId); })
      .then(function (prefs) {
        var payload = window.MFF_YAHOO.buildLeaguePayload({
          leagueId: leagueId,
          name: standings.name,
          teams: standings.teams,
          myTeamId: standings.myTeamId,
          scoringPrefs: prefs
        });
        if (!payload.teams.length) throw new Error("empty league payload");
        return saveLeague(payload).then(function () { return payload; });
      })
      .then(function (payload) {
        setBtn("✓ Saved " + payload.teamCount + " teams — open myfantasyfootball.co", false);
        setTimeout(function () { setBtn("Export league to MFF", false); }, 6000);
      })
      .catch(function (e) {
        console.warn("[MFF/yahoo] export failed:", e);
        setBtn("✗ " + e.message, false);
        setTimeout(function () { setBtn("Export league to MFF", false); }, 6000);
      });
  }

  function inDraftRoom() {
    // Yahoo's draft client renders a distinctive header — keep the export
    // button out of the way during live drafts.
    return /draft/i.test(location.pathname) ||
      !!document.querySelector('[class*="draftclient"], [id*="draft-client"]');
  }

  function mount() {
    if (btn || !leagueIdFromUrl() || inDraftRoom()) return;
    btn = document.createElement("button");
    btn.id = "mffYahooExportBtn";
    btn.textContent = "Export league to MFF";
    btn.style.cssText = [
      "position:fixed", "bottom:18px", "right:18px", "z-index:99999",
      "padding:10px 16px", "border-radius:8px", "border:1px solid #7d2eff",
      "background:#15171c", "color:#c9a4ff", "font:600 13px/1.2 system-ui,sans-serif",
      "cursor:pointer", "box-shadow:0 4px 14px rgba(0,0,0,.4)"
    ].join(";");
    btn.addEventListener("click", onExport);
    document.body.appendChild(btn);
  }

  mount();
  var lastHref = location.href;
  setInterval(function () {
    if (location.href !== lastHref) {
      lastHref = location.href;
      if ((!leagueIdFromUrl() || inDraftRoom()) && btn) { btn.remove(); btn = null; }
      mount();
    }
  }, 1000);
})();
