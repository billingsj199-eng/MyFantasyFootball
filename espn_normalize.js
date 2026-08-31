/* MFF ESPN League Import — normalize.js
 *
 * Pure functions: raw ESPN league JSON → the MFF league payload.
 * No chrome.* / DOM access, so mock.html can load this file directly and
 * exercise the mapping against canned JSON without an ESPN session.
 *
 * ESPN payload shape (v3 API, ?view=mTeam&view=mRoster&view=mSettings):
 *   { id, seasonId, settings:{name, scoringSettings, rosterSettings, draftSettings},
 *     members:[{id, displayName, firstName, lastName}],
 *     teams:[{id, name|location+nickname, owners:[memberId],
 *             record:{overall:{wins, losses, pointsFor}},
 *             roster:{entries:[{playerPoolEntry:{player:{id, fullName,
 *                     defaultPositionId, proTeamId}}}]}}] }
 */
(function (root) {
  "use strict";

  // ESPN defaultPositionId → position label used across the MFF site
  var POS = { 1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "D/ST" };

  // ESPN proTeamId → NFL team abbreviation (ESPN's own canonical mapping)
  var PRO_TEAM = {
    0: "FA", 1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL",
    7: "DEN", 8: "DET", 9: "GB", 10: "TEN", 11: "IND", 12: "KC", 13: "LV",
    14: "LAR", 15: "MIA", 16: "MIN", 17: "NE", 18: "NO", 19: "NYG",
    20: "NYJ", 21: "PHI", 22: "ARI", 23: "PIT", 24: "LAC", 25: "SF",
    26: "SEA", 27: "TB", 28: "WSH", 29: "CAR", 30: "JAX", 33: "BAL", 34: "HOU"
  };

  // ESPN proTeamId → full franchise name. DSTs must be emitted as
  // "<Full Name> D/ST" because that's how the MFF D[] array names them
  // (ESPN's own fullName is just "Ravens D/ST", which the site can't match).
  var PRO_TEAM_FULL = {
    1: "Atlanta Falcons", 2: "Buffalo Bills", 3: "Chicago Bears",
    4: "Cincinnati Bengals", 5: "Cleveland Browns", 6: "Dallas Cowboys",
    7: "Denver Broncos", 8: "Detroit Lions", 9: "Green Bay Packers",
    10: "Tennessee Titans", 11: "Indianapolis Colts", 12: "Kansas City Chiefs",
    13: "Las Vegas Raiders", 14: "Los Angeles Rams", 15: "Miami Dolphins",
    16: "Minnesota Vikings", 17: "New England Patriots", 18: "New Orleans Saints",
    19: "New York Giants", 20: "New York Jets", 21: "Philadelphia Eagles",
    22: "Arizona Cardinals", 23: "Pittsburgh Steelers", 24: "Los Angeles Chargers",
    25: "San Francisco 49ers", 26: "Seattle Seahawks", 27: "Tampa Bay Buccaneers",
    28: "Washington Commanders", 29: "Carolina Panthers", 30: "Jacksonville Jaguars",
    33: "Baltimore Ravens", 34: "Houston Texans"
  };

  // ESPN lineupSlotId → Sleeper-style roster-position label (the shape the MFF
  // site's _mtDetectFormat / _mtBestLineup already understand). IDP and other
  // exotic slots map to null and are skipped.
  var LINEUP_SLOT = {
    0: "QB", 1: "QB" /* TQB */, 2: "RB", 3: "FLEX" /* RB/WR */, 4: "WR",
    5: "FLEX" /* WR/TE */, 6: "TE", 7: "SUPER_FLEX" /* OP */, 16: "DEF",
    17: "K", 20: "BN", 23: "FLEX" /* RB/WR/TE */
    // 21 (IR) intentionally absent — not a roster spot the site should count.
  };

  function teamDisplayName(t) {
    if (t.name && t.name.trim()) return t.name.trim();
    // Pre-2024 payloads split the name into location + nickname
    var parts = [t.location, t.nickname].filter(function (s) { return s && s.trim(); });
    return parts.join(" ").trim() || ("Team " + t.id);
  }

  function ownerName(t, membersById) {
    var m = t.owners && t.owners.length ? membersById[t.owners[0]] : null;
    if (!m) return null;
    if (m.displayName && m.displayName.trim()) return m.displayName.trim();
    return [m.firstName, m.lastName].filter(Boolean).join(" ").trim() || null;
  }

  // Reception points from ESPN scoringSettings. Stat 53 = receptions.
  // Returns the numeric per-reception value (1 → PPR, 0.5 → half, 0 → std).
  function pprValue(settings) {
    try {
      var items = settings.scoringSettings.scoringItems || [];
      for (var i = 0; i < items.length; i++) {
        if (items[i].statId === 53) {
          var pts = items[i].pointsOverrides && items[i].pointsOverrides["16"] != null
            ? items[i].pointsOverrides["16"] : items[i].points;
          return typeof pts === "number" ? pts : 0;
        }
      }
    } catch (_) {}
    return 0;
  }

  function scoringLabel(ppr) {
    if (ppr >= 1) return "ppr";
    if (ppr > 0) return "half";
    return "std";
  }

  // settings.rosterSettings.lineupSlotCounts ({slotId: count}) → Sleeper-style
  // array like ["QB","RB","RB","WR","WR","TE","FLEX","SUPER_FLEX","K","DEF","BN",...]
  function rosterPositions(settings) {
    var out = [];
    try {
      var counts = settings.rosterSettings.lineupSlotCounts || {};
      // Fixed emit order so the array reads starters-first, bench last.
      var order = ["0", "1", "2", "3", "4", "5", "6", "7", "23", "16", "17", "20"];
      order.forEach(function (slotId) {
        var label = LINEUP_SLOT[slotId];
        var n = parseInt(counts[slotId], 10) || 0;
        if (!label || n <= 0) return;
        for (var i = 0; i < n; i++) out.push(label);
      });
    } catch (_) {}
    return out;
  }

  function normalizeSwid(s) {
    return (s || "").replace(/[{}]/g, "").toUpperCase();
  }

  /**
   * Normalize one raw ESPN league JSON blob into the MFF league payload.
   * `swid` (optional) is the user's SWID cookie value — used to flag which
   * team is theirs. Returns null if the blob doesn't look like an ESPN league.
   */
  function normalizeEspnLeague(raw, swid) {
    if (!raw || !raw.id || !Array.isArray(raw.teams)) return null;

    var membersById = {};
    (raw.members || []).forEach(function (m) { membersById[m.id] = m; });
    var mySwid = normalizeSwid(swid);

    var teams = raw.teams.map(function (t) {
      var entries = (t.roster && t.roster.entries) || [];
      var roster = entries.map(function (e) {
        var p = e.playerPoolEntry && e.playerPoolEntry.player;
        if (!p) return null;
        var pos = POS[p.defaultPositionId] || "";
        var name = p.fullName || "";
        if (pos === "D/ST" && PRO_TEAM_FULL[p.proTeamId]) {
          name = PRO_TEAM_FULL[p.proTeamId] + " D/ST";
        }
        return {
          espnId: p.id,
          name: name,
          pos: pos,
          team: PRO_TEAM[p.proTeamId] || ""
        };
      }).filter(Boolean);
      var rec = (t.record && t.record.overall) || {};
      var isMine = !!(mySwid && (t.owners || []).some(function (o) {
        return normalizeSwid(o) === mySwid;
      }));
      return {
        teamId: t.id,
        name: teamDisplayName(t),
        owner: ownerName(t, membersById),
        logo: t.logo || null,
        abbrev: t.abbrev || '',
        isMine: isMine,
        wins: rec.wins || 0,
        losses: rec.losses || 0,
        fpts: Math.round((rec.pointsFor || 0) * 100) / 100,
        roster: roster
      };
    });

    var settings = raw.settings || {};
    var ppr = pprValue(settings);
    var rp = rosterPositions(settings);
    var qbSlots = rp.filter(function (x) { return x === "QB"; }).length;
    var keeperCount = 0;
    try { keeperCount = settings.draftSettings.keeperCount || 0; } catch (_) {}

    // Draft history — present only when the fetch included ?view=mDraftDetail.
    // Names resolve from the roster player map; a pick whose player was
    // dropped post-draft keeps name:null + the playerId so the site can
    // back-fill from ESPN's season players list.
    var draft = null;
    var dd = raw.draftDetail;
    if (dd && dd.drafted && Array.isArray(dd.picks) && dd.picks.length) {
      var playerById = {};
      raw.teams.forEach(function (t) {
        ((t.roster && t.roster.entries) || []).forEach(function (e) {
          var p = e.playerPoolEntry && e.playerPoolEntry.player;
          if (p && p.id != null) playerById[p.id] = p;
        });
      });
      var dtype = "";
      try { dtype = String(settings.draftSettings.type || "").toUpperCase(); } catch (_) {}
      draft = {
        type: dtype || null,
        picks: dd.picks.map(function (p) {
          var pl = playerById[p.playerId];
          var pos = pl ? (POS[pl.defaultPositionId] || "") : "";
          var name = pl ? pl.fullName : null;
          if (pl && pos === "D/ST" && PRO_TEAM_FULL[pl.proTeamId]) {
            name = PRO_TEAM_FULL[pl.proTeamId] + " D/ST";
          }
          return {
            no: p.overallPickNumber, round: p.roundId, rpn: p.roundPickNumber,
            teamId: p.teamId, playerId: p.playerId, name: name, pos: pos
          };
        })
      };
    }

    return {
      platform: "espn",
      leagueId: String(raw.id),
      season: raw.seasonId || null,
      name: settings.name || ("ESPN League " + raw.id),
      scoring: scoringLabel(ppr),
      pprValue: ppr,
      rosterPositions: rp,
      sf: rp.indexOf("SUPER_FLEX") >= 0 || qbSlots >= 2,
      keeper: keeperCount > 0,
      teamCount: teams.length,
      drafted: teams.some(function (t) { return t.roster.length > 0; }),
      draft: draft,
      teams: teams
    };
  }

  root.MFF_ESPN = {
    normalizeEspnLeague: normalizeEspnLeague,
    POS: POS,
    PRO_TEAM: PRO_TEAM,
    PRO_TEAM_FULL: PRO_TEAM_FULL,
    LINEUP_SLOT: LINEUP_SLOT
  };
})(typeof window !== "undefined" ? window : this);
