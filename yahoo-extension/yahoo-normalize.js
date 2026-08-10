/* MFF Yahoo League Import — yahoo-normalize.js
 *
 * Pure functions: parsed Yahoo league page Documents → the MFF league
 * payload (same contract as espn-extension/normalize.js, platform 'yahoo').
 * No chrome.* access and all inputs are Document objects, so
 * mock_league.html can exercise the whole mapping against canned HTML
 * without a Yahoo session.
 *
 * Yahoo has no cookie-auth JSON API (official API is OAuth-only), so the
 * exporter fetches the server-rendered pages same-origin and this file
 * parses them:
 *   - league home /f1/<id>            → standings: teams, records, my team
 *   - team page   /f1/<id>/<teamId>   → roster rows (slot + .ysf-player-name)
 */
(function (root) {
  "use strict";

  // Same slot vocabulary as sidebar.js — Sleeper-style labels the MFF site's
  // _mtDetectFormat/_mtBestLineup already understand.
  var SLOT_MAP = {
    "QB": "QB", "RB": "RB", "WR": "WR", "TE": "TE", "K": "K",
    "DEF": "DEF", "D": "DEF", "D/ST": "DEF", "DST": "DEF",
    "W/R": "WRRB_FLEX", "W/T": "REC_FLEX", "W/R/T": "FLEX", "FLEX": "FLEX",
    "Q/W/R/T": "SUPER_FLEX", "OP": "SUPER_FLEX", "SF": "SUPER_FLEX",
    "BN": "BN", "IR": "IR", "IL": "IR", "IR+": "IR", "IL+": "IR"
  };

  // Yahoo team abbr → full franchise name, for renaming DEF rows to the
  // "<Full Name> D/ST" form the MFF D[] array uses (mirrors the ESPN map).
  var ABBR_FULL = {
    ARI: "Arizona Cardinals", ATL: "Atlanta Falcons", BAL: "Baltimore Ravens",
    BUF: "Buffalo Bills", CAR: "Carolina Panthers", CHI: "Chicago Bears",
    CIN: "Cincinnati Bengals", CLE: "Cleveland Browns", DAL: "Dallas Cowboys",
    DEN: "Denver Broncos", DET: "Detroit Lions", GB: "Green Bay Packers",
    HOU: "Houston Texans", IND: "Indianapolis Colts", JAX: "Jacksonville Jaguars",
    KC: "Kansas City Chiefs", LAC: "Los Angeles Chargers", LAR: "Los Angeles Rams",
    LV: "Las Vegas Raiders", MIA: "Miami Dolphins", MIN: "Minnesota Vikings",
    NE: "New England Patriots", NO: "New Orleans Saints", NYG: "New York Giants",
    NYJ: "New York Jets", PHI: "Philadelphia Eagles", PIT: "Pittsburgh Steelers",
    SEA: "Seattle Seahawks", SF: "San Francisco 49ers", TB: "Tampa Bay Buccaneers",
    TEN: "Tennessee Titans", WSH: "Washington Commanders"
  };

  function fixAbbr(a) {
    a = String(a || "").toUpperCase();
    return a === "WAS" ? "WSH" : a === "JAC" ? "JAX" : a;
  }

  // One roster row's player cell → {name, pos, team}. DEF rows are renamed
  // to the site's "<Full Name> D/ST" form. Returns null for empty slots.
  function parsePlayerCell(row) {
    var box = row.querySelector(".ysf-player-name");
    if (!box) return null;
    var a = box.querySelector("a");
    if (!a) return null;
    var name = a.textContent.trim();
    if (!name) return null;
    var span = box.querySelector("span");
    var meta = span ? span.textContent.trim() : "";
    var mm = meta.match(/([A-Za-z]{2,3})\s*-\s*(QB|WR|RB|TE|K|DEF|D)\b/i);
    var team = mm ? fixAbbr(mm[1]) : "";
    var pos = mm ? mm[2].toUpperCase() : "";
    if (pos === "DEF" || pos === "D") {
      pos = "D/ST";
      if (ABBR_FULL[team]) name = ABBR_FULL[team] + " D/ST";
    }
    return { name: name, pos: pos, team: team };
  }

  // Team page Document → { roster:[{name,pos,team}], slots:[...] }.
  // slots = the starting lineup structure (non-BN/IR), roster = every player
  // on the page including bench and IR.
  function parseTeamDoc(doc) {
    var rows = doc.querySelectorAll("tr");
    var roster = [], slots = [];
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      var cells = row.querySelectorAll("td");
      if (cells.length < 2) continue;
      var slotTok = cells[0].textContent.trim().toUpperCase().replace(/\s+/g, "");
      var slotLbl = SLOT_MAP[slotTok];
      if (!slotLbl) continue;
      if (slotLbl !== "BN" && slotLbl !== "IR") slots.push(slotLbl);
      var info = parsePlayerCell(row);
      if (info) roster.push(info);
    }
    if (!slots.length) return null;
    return { roster: roster, slots: slots };
  }

  // League page Document → { name, teams:[{teamId, name, wins, losses,
  // fpts}], myTeamId }. Team rows are found by their /f1/<id>/<teamId>
  // links; record/points parsed loosely from sibling cells (all-zero in
  // preseason anyway). myTeamId comes from the "My Team" nav link.
  function parseStandingsDoc(doc, leagueId) {
    var seen = {}, teams = [];
    var rows = doc.querySelectorAll("tr");
    var re = new RegExp("/f1/" + leagueId + "/(\\d+)(?:$|[/?#])");
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      var links = row.querySelectorAll("a");
      var teamId = null, name = null;
      for (var j = 0; j < links.length; j++) {
        var href = links[j].getAttribute("href") || "";
        var m = href.match(re);
        if (m && links[j].textContent.trim()) {
          teamId = parseInt(m[1], 10);
          name = links[j].textContent.trim();
          break;
        }
      }
      if (teamId == null || seen[teamId]) continue;
      seen[teamId] = 1;
      var wins = 0, losses = 0, fpts = 0;
      var cells = row.querySelectorAll("td");
      for (var k = 0; k < cells.length; k++) {
        var t = cells[k].textContent.trim();
        var rec = t.match(/^(\d+)-(\d+)(?:-(\d+))?$/);
        if (rec) { wins = parseInt(rec[1], 10); losses = parseInt(rec[2], 10); continue; }
        var pts = t.match(/^([\d,]+\.\d+)$/);
        if (pts && !fpts) fpts = parseFloat(pts[1].replace(/,/g, ""));
      }
      teams.push({ teamId: teamId, name: name, wins: wins, losses: losses, fpts: fpts });
    }

    var myTeamId = null;
    var navLinks = doc.querySelectorAll("a");
    for (var n = 0; n < navLinks.length; n++) {
      if (navLinks[n].textContent.trim().toLowerCase() === "my team") {
        var mm2 = (navLinks[n].getAttribute("href") || "").match(re);
        if (mm2) { myTeamId = parseInt(mm2[1], 10); break; }
      }
    }

    var name2 = "";
    var titleEl = doc.querySelector("title");
    if (titleEl) {
      name2 = titleEl.textContent.split(/\s*[|–-]\s*Yahoo/i)[0].split("|")[0].trim();
    }

    return { name: name2, teams: teams, myTeamId: myTeamId };
  }

  // Assemble the final MFF payload from the per-page parses. `scoringPrefs`
  // is the sidebar's persisted {rec, passTd} for this league (Yahoo settings
  // aren't scrapable) — defaults to Yahoo's ½PPR.
  function buildLeaguePayload(opts) {
    var teams = (opts.teams || []).map(function (t) {
      return {
        teamId: t.teamId,
        name: t.name || ("Team " + t.teamId),
        owner: null,
        isMine: opts.myTeamId != null && t.teamId === opts.myTeamId,
        wins: t.wins || 0,
        losses: t.losses || 0,
        fpts: Math.round((t.fpts || 0) * 100) / 100,
        roster: t.roster || []
      };
    });
    var slots = null;
    for (var i = 0; i < (opts.teams || []).length && !slots; i++) {
      if (opts.teams[i].slots && opts.teams[i].slots.length) slots = opts.teams[i].slots;
    }
    var rp = (slots || []).filter(function (s) { return s !== "IR"; });
    var qbSlots = rp.filter(function (s) { return s === "QB"; }).length;
    var rec = opts.scoringPrefs && opts.scoringPrefs.rec != null ? opts.scoringPrefs.rec : 0.5;
    var now = new Date();
    return {
      platform: "yahoo",
      leagueId: String(opts.leagueId),
      season: now.getMonth() < 2 ? now.getFullYear() - 1 : now.getFullYear(),
      name: opts.name || ("Yahoo League " + opts.leagueId),
      scoring: rec >= 1 ? "ppr" : rec > 0 ? "half" : "std",
      pprValue: rec,
      rosterPositions: rp,
      sf: rp.indexOf("SUPER_FLEX") >= 0 || qbSlots >= 2,
      keeper: false,
      teamCount: teams.length,
      drafted: teams.some(function (t) { return t.roster.length > 0; }),
      teams: teams
    };
  }

  root.MFF_YAHOO = {
    parseTeamDoc: parseTeamDoc,
    parseStandingsDoc: parseStandingsDoc,
    buildLeaguePayload: buildLeaguePayload,
    SLOT_MAP: SLOT_MAP,
    ABBR_FULL: ABBR_FULL
  };
})(typeof window !== "undefined" ? window : this);
