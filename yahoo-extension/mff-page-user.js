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

  // MY RANKS: the user's own boards from the site (versionBoards.mine),
  // shipped as ordered name+pos rows per helper mode so the extension's rec
  // engine can run on the user's custom rankings instead of Jack's.
  var BOARD_TO_MODE = { redraft: "re_1qb", superflex: "re_sf", dynasty: "dyn_1qb", dynastysf: "dyn_sf" };
  function readMyBoards() {
    try {
      var vb = window.versionBoards, D = window.D;
      if (!vb || !vb.mine || !Array.isArray(D) || !D.length) return null;
      // A virgin (never-saved) mine format is a live MIRROR of Jack's premium
      // board (site seeding, 2026-08-10) — shipping it to a free session would
      // leak the full board the sliced bundle just stopped shipping. Custom
      // formats are the user's own work and ship for everyone.
      var u = readUser();
      var prem = !!(u && u.premium);
      var out = {}, any = false;
      for (var k in BOARD_TO_MODE) {
        if (!prem) {
          var custom = false;
          try { custom = !!(window._mineIsCustom && window._mineIsCustom(k)); } catch (_) {}
          if (!custom) continue;
        }
        var arr = vb.mine[k];
        if (!Array.isArray(arr) || !arr.length) continue;
        var rows = [];
        for (var i = 0; i < arr.length; i++) {
          var d = D[arr[i]];
          if (!d || !d.n || !d.s || d._retired) continue;
          rows.push({ n: d.n, s: d.s });
        }
        if (rows.length) { out[BOARD_TO_MODE[k]] = rows; any = true; }
      }
      return any ? out : null;
    } catch (_) { return null; }
  }
  var lastBoards = "";
  function tickBoards() {
    try {
      var b = readMyBoards();
      if (!b) return;
      var h = Object.keys(b).map(function (k) {
        return k + ":" + b[k].length + ":" + b[k].slice(0, 12).map(function (r) { return r.n; }).join(",");
      }).join("|");
      if (h === lastBoards) return;
      lastBoards = h;
      document.dispatchEvent(new CustomEvent("mff-my-rankings-update", {
        detail: { boards: b, syncedAt: Date.now() }
      }));
    } catch (_) {}
  }
  setInterval(tickBoards, 4000);
  setTimeout(tickBoards, 2500);

  // JACKS BOARDS (board-gating Phase B): a PREMIUM session ships Jack's full
  // boards + tier boundaries into the helper. After Phase C flips the rules,
  // the extension's direct Firestore read 403s and this bridge payload is the
  // premium path to the full board — the bundled players.json only carries
  // the free top-36 slice.
  var JACKS_KEYS = { redraft: "rank", superflex: "jSf", dynasty: "jDy", dynastysf: "jDsf" };
  function readJacksBoards() {
    try {
      var u = readUser();
      if (!u || !u.premium) return null;
      var vb = window.versionBoards, D = window.D;
      var vt = window.versionTiers || (typeof versionTiers !== "undefined" ? versionTiers : null);
      if (!vb || !vb.jacks || !Array.isArray(D) || !D.length) return null;
      var boards = {}, tiers = {}, any = false;
      for (var mode in JACKS_KEYS) {
        var key = JACKS_KEYS[mode];
        var arr = vb.jacks[mode];
        if (!Array.isArray(arr) || !arr.length) continue;
        var names = [];
        for (var i = 0; i < arr.length; i++) {
          var d = D[arr[i]];
          if (!d || !d.n || d._retired) continue;
          names.push(d.n);
        }
        if (!names.length) continue;
        boards[key] = names;
        any = true;
        try {
          var tl = vt && vt.jacks && vt.jacks[mode] && vt.jacks[mode].ALL;
          if (Array.isArray(tl) && tl.length) {
            tiers[key] = tl
              .filter(function (t) { return t && t.afterRank >= 1 && t.label; })
              .map(function (t) { return { a: t.afterRank, l: String(t.label), n: String(t.name || "") }; })
              .sort(function (x, y) { return x.a - y.a; });
          }
        } catch (_) {}
      }
      // Current-season OUT FOR SEASON names ride along so the helper's IR
      // flags track live toggles, not just the last players.json export.
      var ir = null;
      try { ir = typeof window._irFlagged === "function" ? window._irFlagged() : null; } catch (_) {}
      return any ? { boards: boards, tiers: tiers, ir: ir } : null;
    } catch (_) { return null; }
  }
  var lastJacks = "";
  function tickJacks() {
    try {
      var j = readJacksBoards();
      if (!j) return;
      var h = Object.keys(j.boards).map(function (k) {
        return k + ":" + j.boards[k].length + ":" + j.boards[k].slice(0, 12).join(",");
      }).join("|") + "§ir:" + (j.ir ? j.ir.join(",") : "");
      if (h === lastJacks) return;
      lastJacks = h;
      document.dispatchEvent(new CustomEvent("mff-jacks-boards-update", {
        detail: { boards: j.boards, tiers: j.tiers, ir: j.ir, syncedAt: Date.now() }
      }));
    } catch (_) {}
  }
  setInterval(tickJacks, 5000);
  setTimeout(tickJacks, 3000);
})();
