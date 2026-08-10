/* MFF ESPN League Import — ws-sniffer.js (MAIN world, document_start)
 *
 * Wraps window.WebSocket (and tags draft-ish fetch URLs) inside ESPN's draft
 * room. Two consumers, both in the ISOLATED world, fed via CustomEvents whose
 * detail is a JSON *string* (Chrome content scripts can't read page objects):
 *
 *  - draft-probe.js   — rolling diagnostic log (chrome.storage + chip)
 *  - sidebar.js       — the live draft helper; parses protocol lines
 *
 * Draft-room protocol (probed live 2026-07-23): line-based text frames —
 *   SELECTING <teamId> <clockMs>          team on the clock
 *   SELECTED  <teamId> <playerId> <n> [<memberSWID>]   pick made
 *   AUTODRAFT <teamId> <true|false>       autodraft toggle
 *
 * Protocol frames are ALWAYS emitted in full (no sampling cap — the helper
 * needs every pick) and buffered so a listener that boots after the socket
 * opened can request a replay ("mff-espn-sniff-replay-request" →
 * "mff-espn-ws-sniff-replay" per buffered event, then live events resume).
 *
 * Passive only: never blocks, modifies, or replays traffic INTO the socket.
 */
(function () {
  "use strict";
  if (window.__mffEspnWsSnifferLoaded) return;
  window.__mffEspnWsSnifferLoaded = true;

  // Match protocol verbs ANYWHERE in the frame — the mid-draft join catch-up
  // packs the full pick history into one frame whose entries are not
  // newline-delimited, and it may not START with a verb either.
  var PROTO_RE = /\b(SELECTING|SELECTED|AUTODRAFT|CLOCK)\s+\d/;
  var buf = [];           // JSON strings of every emitted event, in order
  var BUF_CAP = 5000;

  function emit(obj, replayOnly) {
    var s;
    try { s = JSON.stringify(obj); } catch (_) { return; }
    if (!replayOnly) {
      buf.push(s);
      if (buf.length > BUF_CAP) buf = buf.slice(-Math.floor(BUF_CAP * 0.8));
    }
    try {
      document.dispatchEvent(new CustomEvent(
        replayOnly ? "mff-espn-ws-sniff-replay" : "mff-espn-ws-sniff",
        { detail: s }
      ));
    } catch (_) {}
  }

  // A late-booting listener asks for everything captured so far.
  document.addEventListener("mff-espn-sniff-replay-request", function () {
    for (var i = 0; i < buf.length; i++) {
      try {
        document.dispatchEvent(new CustomEvent("mff-espn-ws-sniff-replay", { detail: buf[i] }));
      } catch (_) {}
    }
    try {
      document.dispatchEvent(new CustomEvent("mff-espn-ws-sniff-replay", {
        detail: JSON.stringify({ ev: "replay-done", count: buf.length })
      }));
    } catch (_) {}
  });

  // ── WebSocket wrap ──────────────────────────────────────────────────
  var NativeWS = window.WebSocket;
  var wsCount = 0;
  window.WebSocket = function (url, protocols) {
    var ws = protocols !== undefined ? new NativeWS(url, protocols) : new NativeWS(url);
    var id = ++wsCount;
    var msgN = 0, plainSamples = 0, otherSamples = 0;
    emit({ ev: "ws-open", id: id, url: String(url).slice(0, 300) });
    ws.addEventListener("close", function (e) {
      emit({ ev: "ws-close", id: id, code: e.code, totalMsgs: msgN });
    });
    ws.addEventListener("message", function (m) {
      msgN++;
      try {
        if (typeof m.data === "string") {
          if (PROTO_RE.test(m.data)) {
            // Draft-protocol frame: ALWAYS emit. Cap generously — the join
            // catch-up can carry an entire draft's picks in one frame
            // (192 picks ≈ 11 KB).
            emit({ ev: "proto", id: id, n: msgN, data: m.data.slice(0, 30000) });
          } else if (/pick|draft|onclock|select|roster/i.test(m.data) && otherSamples < 30) {
            otherSamples++;
            emit({ ev: "ws-msg", id: id, n: msgN, interesting: true, sample: m.data.slice(0, 400) });
          } else if (plainSamples < 5) {
            plainSamples++;
            emit({ ev: "ws-msg", id: id, n: msgN, interesting: false, sample: m.data.slice(0, 400) });
          } else if (msgN % 100 === 0) {
            emit({ ev: "ws-heartbeat", id: id, n: msgN });
          }
        } else if (msgN <= 3) {
          emit({ ev: "ws-msg-binary", id: id, n: msgN, bytes: (m.data && m.data.byteLength) || null });
        }
      } catch (_) {}
    });
    return ws;
  };
  window.WebSocket.prototype = NativeWS.prototype;
  try {
    window.WebSocket.CONNECTING = NativeWS.CONNECTING;
    window.WebSocket.OPEN = NativeWS.OPEN;
    window.WebSocket.CLOSING = NativeWS.CLOSING;
    window.WebSocket.CLOSED = NativeWS.CLOSED;
  } catch (_) {}

  // ── fetch URL tagging (some rooms poll instead of/alongside sockets) ─
  var nativeFetch = window.fetch;
  window.fetch = function (input) {
    try {
      var url = typeof input === "string" ? input : (input && input.url) || "";
      if (/draft/i.test(url)) emit({ ev: "fetch", url: String(url).slice(0, 300) });
    } catch (_) {}
    return nativeFetch.apply(this, arguments);
  };
})();
