// MFF Yahoo Helper — endpoint probe (MAIN world, document_start).
// Yahoo's fantasy web pages are mostly server-rendered; whatever JSON they DO
// fetch client-side is the upgrade path from DOM scraping to an API-driven
// helper (the same probe-first play that cracked the ESPN draft room).
// Passively wraps fetch + XMLHttpRequest and records same-site request URLs
// (no bodies, no auth material). v0.3.0 also wraps WebSocket — the draft
// client's live pick feed almost certainly rides a WS, and its frames are
// exactly what the future DRAFT mode needs to parse. Frames are truncated,
// capped, and only captured on draft-ish pages. The sidebar content script
// listens for the events and persists a rolling log to chrome.storage
// `mff_yahoo_probe`; SETTINGS has a COPY PROBE LOG button.
(() => {
  'use strict';
  if (window.__mffYahooProbe) return;
  const seen = new Set();
  const MAX = 200;
  const MAX_FRAMES = 300;
  const FRAME_CHARS = 400;
  let frames = 0;
  window.__mffYahooProbe = { urls: [] };
  function emit(kind, payload) {
    try {
      window.__mffYahooProbe.urls.push({ t: Date.now(), kind, url: payload });
      console.log('[MFF/yahoo-probe]', kind, payload);
      document.dispatchEvent(new CustomEvent('mff-yahoo-probe', {
        detail: JSON.stringify({ kind, url: payload }),
      }));
    } catch (_) {}
  }
  function record(kind, url) {
    try {
      const u = String(url);
      if (!/fantasysports\.yahoo\.com|yahooapis\.com|graphite|\/api\/|^wss?:/i.test(u)) return;
      const key = u.replace(/([?&][^=&]+)=[^&]*/g, '$1='); // strip param values
      if (seen.has(key) || seen.size >= MAX) return;
      seen.add(key);
      emit(kind, key);
    } catch (_) {}
  }
  function recordFrame(kind, data) {
    try {
      if (typeof data !== 'string') { data = '[binary ' + (data && data.byteLength || '?') + 'b]'; }
      // ALWAYS dispatch the FULL frame — draft-mode consumes these live, and
      // the P| replay frame alone runs ~2KB (truncating it corrupts pick
      // catch-up after a mid-draft refresh). The 400-char cut + entry cap
      // apply only to the persisted probe log / console noise.
      frames++;
      document.dispatchEvent(new CustomEvent('mff-yahoo-probe', {
        detail: JSON.stringify({ kind, url: data }),
      }));
      if (frames <= MAX_FRAMES) {
        window.__mffYahooProbe.urls.push({ t: Date.now(), kind, url: data.slice(0, FRAME_CHARS) });
        console.log('[MFF/yahoo-probe]', kind, data.slice(0, 120));
      }
    } catch (_) {}
  }
  const origFetch = window.fetch;
  window.fetch = function (input, init) {
    try { record('fetch', typeof input === 'string' ? input : (input && input.url)); } catch (_) {}
    return origFetch.apply(this, arguments);
  };
  const origOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (method, url) {
    try { record('xhr', url); } catch (_) {}
    return origOpen.apply(this, arguments);
  };
  // WebSocket wrap: record every socket URL; capture frames only in the
  // draft client (URL heuristic) so season pages don't flood the log.
  const draftish = () => /draft/i.test(location.pathname) || /draft/i.test(location.search);
  const OrigWS = window.WebSocket;
  if (OrigWS) {
    window.WebSocket = function (url, protocols) {
      const ws = protocols !== undefined ? new OrigWS(url, protocols) : new OrigWS(url);
      try {
        record('ws-open', url);
        if (draftish()) {
          ws.addEventListener('message', (e) => recordFrame('ws-msg', e.data));
          const origSend = ws.send.bind(ws);
          ws.send = function (data) { try { recordFrame('ws-send', data); } catch (_) {} return origSend(data); };
        }
      } catch (_) {}
      return ws;
    };
    window.WebSocket.prototype = OrigWS.prototype;
    Object.getOwnPropertyNames(OrigWS).forEach((k) => {
      try { if (!(k in window.WebSocket)) window.WebSocket[k] = OrigWS[k]; } catch (_) {}
    });
  }
})();
