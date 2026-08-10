/* MFF live-watcher v0.9.98 — pick-ribbon DOM scanner + live pick dispatcher.
 *
 * v0.9.98:
 *   - Parses POS - TEAM out of each card and passes `team` along with the
 *     player name. Sidebar's findPlayerLoose uses team to disambiguate
 *     initial+lastname names ("B. Robinson" → ATL = Bijan, WAS = Brian).
 *
 * v0.9.97 anchor strategy: anchor on the POS-TEAM cell instead of the
 * pick number. The user's actual DOM has the username+pick in one tiny
 * inner element and the player+POS-TEAM in a separate sibling, so
 * anchoring on either alone needed walking up to a common ancestor.
 */
(function () {
  "use strict";
  if (window.__mffLiveWatcherLoaded) return;
  window.__mffLiveWatcherLoaded = true;

  var POLL_MS = 1500;
  var POS_TOKENS = "(QB|RB|WR|TE|K|DST|D\\/ST)";
  var PICK_NUM_RE = /(\d+)\.(\d+)\s*\|\s*(\d+)/;
  // Capture the team abbrev too — we'll pass it to sidebar for name disambig.
  // v0.10.46: the "- TEAM" portion is now OPTIONAL. Free agents (Diggs,
  // Deebo, etc.) render on Underdog with just a position and no NFL team
  // ("WR" / "WR -" rather than "WR - PHI"), so the old team-required anchor
  // never matched their pick cards — meaning a drafted FA was never detected
  // and stayed on the MFF board forever. Optional team fixes removal for
  // FAs while still capturing the team when present. No false-pick risk: a
  // card only counts once it also has a `round.pick | overall` ancestor,
  // which only exists in the live pick ribbon.
  var POS_TEAM_RE_ANCHOR = new RegExp("^\\s*" + POS_TOKENS + "(?:\\s*[-\\u2013\\u2014]\\s*([A-Z]{2,4})?)?\\s*$");

  function ownText(el) {
    if (!el || !el.childNodes) return "";
    var out = "";
    for (var i = 0; i < el.childNodes.length; i++) {
      var n = el.childNodes[i];
      if (n.nodeType === 3) out += n.textContent || "";
    }
    return out.trim();
  }

  var BLOCK_TAGS = { DIV:1, P:1, LI:1, SECTION:1, ARTICLE:1, H1:1, H2:1, H3:1, H4:1, H5:1, H6:1, BR:1, TR:1, TD:1, TH:1, BUTTON:1, A:1 };
  function collectVisualLines(root) {
    var lines = [];
    var current = "";
    function flush() {
      var v = current.replace(/\s+/g, " ").trim();
      if (v) lines.push(v);
      current = "";
    }
    function walk(node) {
      if (!node) return;
      if (node.nodeType === 3) { current += node.textContent || ""; return; }
      if (node.nodeType !== 1) return;
      var tag = node.nodeName || "";
      var isBlock = !!BLOCK_TAGS[tag];
      if (isBlock) flush();
      if (tag === "BR") { flush(); return; }
      for (var i = 0; i < node.childNodes.length; i++) walk(node.childNodes[i]);
      if (isBlock) flush();
    }
    walk(root);
    flush();
    return lines;
  }

  // v0.10.58: persistent parse-failure log. Ribbon cards that anchor on a
  // position + have a pick-number ancestor but still fail to parse (the
  // suspected FA-card path) get recorded here so the card's exact DOM
  // shape can be inspected AFTER the fact via __mffScanRejects — the
  // ribbon scrolls old cards out of the DOM within minutes, so a live
  // repro was previously required. Deduped + capped; survives until the
  // page reloads. Note: upcoming-team cards (QB/RB/WR/TE count grids)
  // legitimately land here as "empty-name" — look for entries whose lines
  // contain an actual player name.
  var _rejects = [];
  var _rejectKeys = new Set();
  function recordReject(reason, anchor, lines) {
    try {
      var key = reason + "|" + anchor + "|" + (lines || []).slice(0, 6).join("/");
      if (_rejectKeys.has(key) || _rejects.length >= 60) return;
      _rejectKeys.add(key);
      _rejects.push({ reason: reason, anchor: anchor, lines: (lines || []).slice(0, 10), at: new Date().toISOString() });
    } catch (_) {}
  }
  window.__mffScanRejects = _rejects;

  function scanPicks(debug) {
    var picks = [];
    var seenPickNums = new Set();
    var debugInfo = { posAnchors: 0, withPickAncestor: 0, parsed: 0, sampleAnchors: [], rejectedNoPickAncestor: [], rejectedParse: [] };

    var posAnchors = [];
    var all = document.querySelectorAll("*");
    for (var i = 0; i < all.length; i++) {
      var el = all[i];
      var ot = ownText(el);
      if (!ot || ot.length > 30) continue;
      if (POS_TEAM_RE_ANCHOR.test(ot)) posAnchors.push(el);
    }
    debugInfo.posAnchors = posAnchors.length;

    var seenCards = new Set();
    for (var a = 0; a < posAnchors.length; a++) {
      var anchor = posAnchors[a];
      var anchorPosText = ownText(anchor);
      var anchorMatch = anchorPosText.match(POS_TEAM_RE_ANCHOR);
      var teamAbbr = anchorMatch && anchorMatch[2] ? anchorMatch[2] : "";
      if (debug && a < 5) debugInfo.sampleAnchors.push(anchorPosText);

      var posAbbr = anchorMatch && anchorMatch[1] ? anchorMatch[1] : "";
      var card = anchor.parentElement;
      var hops = 0;
      var cardText = "";
      var pickMatch = null;
      while (card && hops < 12) {
        cardText = card.textContent || "";
        pickMatch = cardText.match(PICK_NUM_RE);
        if (pickMatch) break;
        card = card.parentElement;
        hops++;
      }
      if (!pickMatch || !card) {
        if (debug && debugInfo.rejectedNoPickAncestor.length < 5) {
          debugInfo.rejectedNoPickAncestor.push(anchorPosText);
        }
        continue;
      }
      debugInfo.withPickAncestor++;

      var pickNum = parseInt(pickMatch[3], 10);
      if (!pickNum || pickNum < 1 || pickNum > 500) continue;
      if (seenPickNums.has(pickNum)) continue;
      if (seenCards.has(card)) continue;
      seenCards.add(card);

      var lines = collectVisualLines(card);
      if (!lines.length) continue;

      var pickIdx = -1;
      for (var k = 0; k < lines.length; k++) {
        if (PICK_NUM_RE.test(lines[k])) { pickIdx = k; break; }
      }
      var posIdx = -1;
      for (var k2 = (pickIdx >= 0 ? pickIdx + 1 : 0); k2 < lines.length; k2++) {
        if (POS_TEAM_RE_ANCHOR.test(lines[k2])) { posIdx = k2; break; }
      }
      if (pickIdx === -1 || posIdx === -1) {
        if (debug && debugInfo.rejectedParse.length < 5) {
          debugInfo.rejectedParse.push({ anchor: anchorPosText, lines: lines.slice(0, 8) });
        }
        recordReject("no-pick-or-pos-line", anchorPosText, lines);
        continue;
      }

      var nameParts = [];
      for (var j = pickIdx + 1; j < posIdx; j++) {
        var ln = lines[j];
        if (!ln || ln.length < 2 || ln.length > 40) continue;
        if (/^\d+$/.test(ln)) continue;
        if (/^[\d\s]+$/.test(ln)) continue;
        if (PICK_NUM_RE.test(ln)) continue;
        nameParts.push(ln);
      }
      var name = nameParts.join(" ").replace(/\s+/g, " ").trim();
      if (!name || name.length > 40) {
        recordReject("empty-name", anchorPosText, lines);
        continue;
      }

      seenPickNums.add(pickNum);
      picks.push({ name: name, pickNum: pickNum, team: teamAbbr, pos: posAbbr });
      debugInfo.parsed++;
    }

    picks.sort(function (a, b) { return a.pickNum - b.pickNum; });
    if (debug) picks._debug = debugInfo;
    return picks;
  }

  // Underdog's own "Pick position" readout in the on-the-clock card is the
  // most direct statement of which slot you are — no username matching, no
  // snake derivation from a highlight.
  //
  // sidebar.js has always CALLED window.__mffDetectMySlot(), but nothing in
  // this extension ever DEFINED it, so auto-detect could never fire and
  // state.slot stayed null unless you clicked a slot by hand. With no slot,
  // isMyTurn() matches nothing, myRoster stays empty ("0 mine" in the header),
  // and every roster-aware signal in the engine — position multipliers, the
  // BBM value chart, the prefix-build history, need, positional quality —
  // silently evaluates against an empty team.
  window.__mffDetectMySlot = function () {
    try {
      const MAX_SLOT = 24;
      const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      for (let n = walk.nextNode(); n; n = walk.nextNode()) {
        if (!/^\s*pick\s+position\s*$/i.test(n.nodeValue || "")) continue;
        // Climb until an ancestor holds both the label and its number.
        let el = n.parentElement;
        for (let i = 0; el && i < 5; el = el.parentElement, i++) {
          const txt = (el.textContent || "").replace(/\s+/g, " ");
          const m = txt.match(/(\d{1,2})\s*Pick position/i) ||
                    txt.match(/Pick position\s*(\d{1,2})/i);
          if (m) {
            const slot = parseInt(m[1], 10);
            if (slot >= 1 && slot <= MAX_SLOT) {
              return { slot: slot, source: "pickposition" };
            }
          }
        }
      }
    } catch (e) { /* detection is best-effort — never break the room */ }
    return null;
  };

  window.__mffBootstrap = function () {
    try {
      var p = scanPicks(true);
      console.log("[MFF/live-watcher] bootstrap found", p.length, "picks", p._debug || "");
      delete p._debug;
      return p;
    } catch (e) {
      console.warn("[MFF/live-watcher] bootstrap error:", e);
      return [];
    }
  };

  window.__mffDebugScan = function () {
    var p = scanPicks(true);
    console.log("[MFF/debug] picks:", p);
    console.log("[MFF/debug] info:", p._debug);
    return p;
  };

  var seenLive = new Set();
  var _initialMaxPickAtStart = 0;

  function pollOnce() {
    try {
      var picks = scanPicks(false);
      if (!picks || !picks.length) return;
      for (var i = 0; i < picks.length; i++) {
        var p = picks[i];
        var key = p.pickNum + "::" + p.name;
        if (seenLive.has(key)) continue;
        seenLive.add(key);
        if (p.pickNum <= _initialMaxPickAtStart) continue;
        try {
          window.postMessage({
            source: "mff-underdog",
            type: "pick",
            player: p.name,
            pickNum: p.pickNum,
            team: p.team,
            pos: p.pos
          }, "*");
        } catch (_) {}
      }
    } catch (e) { /* swallow */ }
  }

  function recordInitialBaseline() {
    try {
      var initial = scanPicks(false);
      for (var i = 0; i < initial.length; i++) {
        seenLive.add(initial[i].pickNum + "::" + initial[i].name);
        if (initial[i].pickNum > _initialMaxPickAtStart) _initialMaxPickAtStart = initial[i].pickNum;
      }
      console.log("[MFF/live-watcher] baseline scanned", initial.length, "picks; max pickNum =", _initialMaxPickAtStart);
    } catch (_) {}
  }

  function start() {
    recordInitialBaseline();
    setInterval(pollOnce, POLL_MS);
    console.log("[MFF/live-watcher] v0.10.58 ready — __mffDebugScan() to inspect, __mffScanRejects for parse failures");
  }

  if (document.body) setTimeout(start, 1000);
  else window.addEventListener("DOMContentLoaded", function () { setTimeout(start, 1000); });
})();
