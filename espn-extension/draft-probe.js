/* MFF ESPN League Import — draft-probe.js (isolated world, document_idle)
 *
 * Phase-1 draft-feed PROBE. Answers: how do we get live picks for an ESPN
 * draft helper? Two candidate paths, both instrumented here:
 *
 *   Path 1 — poll ?view=mDraftDetail (only possible in REAL league drafts,
 *            where the URL has a leagueId; mock-lobby drafts have no
 *            API-readable league). Logs whether picksMade climbs DURING the
 *            draft or only appears at the end.
 *   Path 2 — the room's own live feed, captured by ws-sniffer.js (MAIN
 *            world) and forwarded here as CustomEvents. Works in mocks too.
 *
 * Everything lands in one rolling log: console (`[MFF/espn-draft-probe]`),
 * chrome.storage.local `mff_espn_draft_probe` (latest run wins), and an
 * amber "MFF PROBE" chip (bottom-left) — click it to copy the full log JSON
 * to the clipboard for analysis.
 */
(function () {
  "use strict";
  if (window.__mffEspnDraftProbeLoaded) return;
  window.__mffEspnDraftProbeLoaded = true;

  var API = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/";
  var startedAt = Date.now();
  var log = [];
  var chip = null;
  var pollN = 0, lastPickCount = -1, pollTimer = null;

  function leagueIdFromUrl() {
    try {
      var m = new URLSearchParams(location.search).get("leagueId");
      return m && /^\d+$/.test(m) && m !== "0" ? m : null;
    } catch (_) { return null; }
  }
  function season() {
    var now = new Date();
    return String(now.getMonth() < 2 ? now.getFullYear() - 1 : now.getFullYear());
  }
  function isDraftishPage() {
    return /draft/i.test(location.pathname + location.search);
  }

  function persist() {
    try {
      if (!chrome || !chrome.runtime || !chrome.runtime.id) return;
      // Don't clobber a recorded draft-room log from ordinary fantasy pages —
      // only persist once this page is draft-ish or has captured feed data.
      if (!isDraftishPage() && !log.some(function (e) { return e.src === "sniffer" || e.src === "api"; })) return;
      chrome.storage.local.set({
        mff_espn_draft_probe: {
          startedAt: startedAt,
          url: location.href,
          savedAt: Date.now(),
          entries: log
        }
      });
    } catch (_) {}
  }
  function record(entry) {
    entry.t = Date.now();
    log.push(entry);
    if (log.length > 600) log = log.slice(-500);
    persist();
  }

  // ── Dump relay: lets ANY fantasy.espn.com page (e.g. a debugging session
  // in another tab) read the persisted probe log — dispatch
  // "mff-espn-probe-dump-request" on document, listen for
  // "mff-espn-probe-dump" (detail = JSON string). chrome.storage is shared
  // across the extension's tabs, so this reaches logs a draft tab recorded.
  document.addEventListener("mff-espn-probe-dump-request", function () {
    try {
      if (!chrome || !chrome.runtime || !chrome.runtime.id) return;
      chrome.storage.local.get(null, function (all) {
        var out = {};
        for (var k in all) {
          if (k === "mff_espn_draft_probe" || k.indexOf("espnPicks_") === 0 || k.indexOf("espnDraft_") === 0) {
            out[k] = all[k];
          }
        }
        try {
          document.dispatchEvent(new CustomEvent("mff-espn-probe-dump", {
            detail: JSON.stringify(out)
          }));
        } catch (_) {}
      });
    } catch (_) {}
  });

  // ── Path 2: findings forwarded from ws-sniffer.js (MAIN world) ───────
  document.addEventListener("mff-espn-ws-sniff", function (e) {
    try {
      var d = JSON.parse(e.detail);
      d.src = "sniffer";
      record(d);
      console.log("[MFF/espn-draft-probe]", d.ev, d);
      mountChip(); // WS traffic on a draft page → make sure the chip is up
    } catch (_) {}
  });

  // ── Path 1: mDraftDetail polling (real leagues only) ─────────────────
  function poll() {
    var id = leagueIdFromUrl();
    if (!id) return;
    pollN++;
    fetch(API + season() + "/segments/0/leagues/" + id + "?view=mDraftDetail", {
      credentials: "include",
      headers: { Accept: "application/json" }
    }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    }).then(function (j) {
      var dd = j.draftDetail || {};
      var picks = Array.isArray(dd.picks) ? dd.picks : [];
      // playerId is -1 (truthy!) on unmade slots — only count real ids
      var made = picks.filter(function (p) { return p && p.playerId > 0; }).length;
      var last = null;
      for (var i = picks.length - 1; i >= 0; i--) {
        if (picks[i] && picks[i].playerId > 0) { last = picks[i]; break; }
      }
      var changed = made !== lastPickCount;
      if (changed || pollN % 12 === 1) { // every change + ~1/min heartbeat
        record({
          src: "api", poll: pollN, ok: true,
          drafted: !!dd.drafted, inProgress: !!dd.inProgress,
          totalSlots: picks.length, picksMade: made,
          delta: lastPickCount < 0 ? null : made - lastPickCount,
          lastPick: last ? {
            overall: last.overallPickNumber || null,
            round: last.roundId || null,
            teamId: last.teamId || null,
            playerId: last.playerId || null,
            auto: !!last.autoDraftTypeId
          } : null
        });
        console.log("[MFF/espn-draft-probe] api poll", pollN,
          "picksMade=" + made + "/" + picks.length,
          "inProgress=" + dd.inProgress, "drafted=" + dd.drafted, last || "");
      }
      lastPickCount = made;
      setChip("MFF PROBE · " + made + (picks.length ? "/" + picks.length : "") + " picks");
    }).catch(function (e) {
      record({ src: "api", poll: pollN, ok: false, error: String((e && e.message) || e) });
      console.warn("[MFF/espn-draft-probe] api poll failed:", e);
      setChip("MFF PROBE · api error");
    });
  }

  // ── Chip UI ──────────────────────────────────────────────────────────
  function setChip(text) { if (chip) chip.textContent = text; }
  function mountChip() {
    if (chip || !document.body) return;
    chip = document.createElement("div");
    chip.id = "mffEspnProbeChip";
    chip.textContent = "MFF PROBE · recording";
    chip.title = "MFF draft-feed probe is recording. Click to copy the probe log (JSON) to your clipboard.";
    chip.style.cssText = [
      "position:fixed", "bottom:14px", "left:14px", "z-index:2147483647",
      "padding:7px 12px", "border-radius:7px", "border:1px solid #fbbf24",
      "background:#111827", "color:#fbbf24",
      "font:600 12px/1.2 system-ui,sans-serif", "cursor:pointer",
      "box-shadow:0 4px 14px rgba(0,0,0,.45)", "user-select:none"
    ].join(";");
    chip.addEventListener("click", function () {
      var payload = JSON.stringify({ startedAt: startedAt, url: location.href, entries: log }, null, 1);
      var done = function () {
        setChip("MFF PROBE · copied " + log.length + " entries ✓");
        setTimeout(function () { setChip("MFF PROBE · recording (" + log.length + ")"); }, 3000);
      };
      try {
        navigator.clipboard.writeText(payload).then(done, function () {
          console.log("[MFF/espn-draft-probe] FULL LOG:\n" + payload);
          setChip("MFF PROBE · see console");
        });
      } catch (_) {
        console.log("[MFF/espn-draft-probe] FULL LOG:\n" + payload);
        setChip("MFF PROBE · see console");
      }
    });
    document.body.appendChild(chip);
  }

  // ── Boot ─────────────────────────────────────────────────────────────
  if (isDraftishPage()) mountChip();
  record({ src: "boot", url: location.href, leagueId: leagueIdFromUrl(), draftish: isDraftishPage() });
  console.log("[MFF/espn-draft-probe] armed on", location.href,
    "· leagueId:", leagueIdFromUrl() || "(none — mock? API polling off, WS sniffing on)");
  if (leagueIdFromUrl()) {
    poll();
    pollTimer = setInterval(poll, 5000);
  }
  // SPA navigation: start/stop polling as leagueId appears/disappears
  var lastHref = location.href;
  setInterval(function () {
    if (location.href === lastHref) return;
    lastHref = location.href;
    record({ src: "nav", url: location.href, leagueId: leagueIdFromUrl(), draftish: isDraftishPage() });
    if (isDraftishPage()) mountChip();
    if (leagueIdFromUrl() && !pollTimer) { poll(); pollTimer = setInterval(poll, 5000); }
  }, 1500);
})();
