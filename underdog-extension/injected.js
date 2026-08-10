/* MFF Underdog Draft Helper — main-world hook
 *
 * v0.9.23: switched from "issue our own API call" to "passively snoop the
 * responses Underdog already fetches." That dodges every CORS / auth /
 * preflight problem with making a duplicate request — we just read the
 * page's own XHR responses as they arrive.
 *
 * Live testing showed Underdog uses XHR for:
 *   /v4/user/active_drafts          — drafts in progress
 *   /v2/user/completed_slates       — completed drafts (= portfolio history)
 *   /v1/user, /v1/user/profile      — user info
 *
 * We hook XMLHttpRequest.open + send and stash response bodies for
 * underdogfantasy.com URLs by their path. When the sidebar requests sync,
 * we hand it whatever's in the cache — fresh, real, and origin-correct.
 */
(function () {
  "use strict";
  if (window.__mffMainHookLoaded) return;
  window.__mffMainHookLoaded = true;

  // v0.9.25: persist cache via sessionStorage so navigating between
  // /active and /completed (full page reloads inside a SPA tab) doesn't
  // wipe what we've already snooped. sessionStorage is per-origin +
  // per-tab, which exactly matches our scope.
  var STORAGE_KEY = '__mffUDCache_v1';
  function loadCache() {
    try {
      var raw = sessionStorage.getItem(STORAGE_KEY);
      if (raw) return JSON.parse(raw) || {};
    } catch (_) {}
    return {};
  }
  function saveCache() {
    try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify(window.__mffUDCache)); } catch (_) {}
  }
  window.__mffUDCache = loadCache();

  // v0.10.47: pagination-aware cache write. Underdog paginates its list
  // endpoints — the "Load more" button on a tournament's "Your teams" list
  // fires /v1/user/tournament_rounds/<id>/drafts?page=N. We key the cache by
  // pathname only (query string dropped), so WITHOUT merging, page 2 would
  // clobber page 1 under the same key and the sync would only ever see one
  // page of teams. Concatenate known list arrays (de-duped by id, newest item
  // wins) so every page the user loads accumulates under the single key.
  var LIST_KEYS = ['drafts', 'slates', 'completed_slates', 'entries',
                   'draft_entries', 'user_drafts', 'tournament_rounds'];
  function mergeListData(oldData, newData) {
    if (!oldData || typeof oldData !== 'object' ||
        !newData || typeof newData !== 'object' ||
        Array.isArray(oldData) || Array.isArray(newData)) {
      return newData;
    }
    var merged = Object.assign({}, oldData, newData); // newData scalars/meta win
    var didMerge = false;
    for (var i = 0; i < LIST_KEYS.length; i++) {
      var k = LIST_KEYS[i];
      if (!Array.isArray(oldData[k]) || !Array.isArray(newData[k])) continue;
      var order = [], byId = {}, noId = [];
      oldData[k].concat(newData[k]).forEach(function (item) {
        var id = (item && item.id != null) ? item.id : null;
        if (id == null) { noId.push(item); return; }
        if (!(id in byId)) order.push(id);
        byId[id] = item; // later occurrence (newData) wins → freshest data
      });
      merged[k] = order.map(function (id) { return byId[id]; }).concat(noId);
      didMerge = true;
    }
    return didMerge ? merged : newData;
  }
  function writeCache(key, data, url) {
    var existing = window.__mffUDCache[key];
    var finalData = (existing && existing.data)
      ? mergeListData(existing.data, data)
      : data;
    window.__mffUDCache[key] = { data: finalData, ts: Date.now(), fullUrl: url };
    saveCache();
  }

  function captureToken(token, source) {
    if (typeof token !== 'string') return;
    if (token.indexOf('Bearer') !== 0) return;
    if (window.__mffUDAuth === token) return;
    window.__mffUDAuth = token;
    console.log('[MFF/inject] captured Underdog auth token via', source);
  }

  function pathOf(url) {
    try {
      var u = new URL(url, location.href);
      return u.pathname;
    } catch (_) { return url; }
  }

  // v0.10.1: dual-domain — UD is migrating from underdogfantasy.com to
  // underdogsports.com. Recognize both during the transition so XHR snooping
  // keeps working regardless of which host UD's app calls.
  var UD_HOST_RE = /(underdogfantasy|underdogsports)\.com/;

  function shouldCache(url) {
    if (!url || !UD_HOST_RE.test(url)) return false;
    var p = pathOf(url);
    // v0.9.37: also cache /teams (needed to resolve team_id → abbrev)
    // and /scoring_types responses (entry-style/contest-style metadata).
    return /(draft|appearance|slate|entr|pool|exposur|portfolio|\/teams|\/scoring_types|\/v\d+\/user(\b|\/))/.test(p);
  }

  // v0.9.51: capture the FULL header set UD's own SPA sets per URL pattern
  // so we can replay it on our own XHRs. UD requires custom headers beyond
  // just Authorization; without them the API returns 401 even with a valid
  // token. Stored by URL prefix (e.g., "/v2/drafts/") so any past UD call
  // to a similar endpoint informs our request.
  window.__mffUDHeaders = window.__mffUDHeaders || {};

  // v0.9.53: capture the query parameters UD passes to every API call.
  // Network trace showed UD requires these on ALL user-scoped endpoints:
  //   ?product=fantasy
  //   &product_experience_id=018e1234-5678-9abc-def0-123456789002   (constant for NFL fantasy)
  //   &state_config_id=f8996742-f10c-4d32-955a-dcbcaa5dc5c0          (user's regulatory state)
  // Without these, the API returns 401 — the smoking gun behind the
  // "auth token alone isn't enough" mystery. We capture them once from any
  // UD XHR and reuse on our own calls.
  window.__mffUDParams = window.__mffUDParams || {};
  function _captureParamsFromUrl(url) {
    try {
      var u = new URL(url, location.href);
      var sp = u.searchParams;
      ['product', 'product_experience_id', 'state_config_id'].forEach(function (k) {
        var v = sp.get(k);
        if (v) window.__mffUDParams[k] = v;
      });
    } catch (_) {}
  }
  function _ensureParams(url) {
    try {
      var u = new URL(url, location.href);
      var changed = false;
      ['product', 'product_experience_id', 'state_config_id'].forEach(function (k) {
        if (!u.searchParams.has(k) && window.__mffUDParams[k]) {
          u.searchParams.set(k, window.__mffUDParams[k]);
          changed = true;
        }
      });
      return changed ? u.toString() : url;
    } catch (_) {
      return url;
    }
  }

  // --- XHR wrap: capture auth + responses + headers ---
  var _xhrOpen = XMLHttpRequest.prototype.open;
  var _xhrSetHeader = XMLHttpRequest.prototype.setRequestHeader;
  var _xhrSend = XMLHttpRequest.prototype.send;

  XMLHttpRequest.prototype.open = function (method, url) {
    try {
      this.__mffUrl = url;
      this.__mffMethod = method;
      this.__mffHeaders = {};
    } catch (_) {}
    return _xhrOpen.apply(this, arguments);
  };

  XMLHttpRequest.prototype.setRequestHeader = function (name, value) {
    try {
      if (name && name.toLowerCase() === 'authorization') captureToken(value, 'XHR');
      // Track every header UD sets so we can replay them
      if (this.__mffHeaders && name) this.__mffHeaders[name] = value;
    } catch (_) {}
    return _xhrSetHeader.apply(this, arguments);
  };

  XMLHttpRequest.prototype.send = function () {
    try {
      var url = this.__mffUrl || '';
      // v0.9.54: skip our own self-fetch XHRs from polluting the captured
      // UD-headers cache. Without this flag, our 2-header mainfetch XHR
      // would overwrite UD's 11-header capture for the same URL prefix
      // and the next mainfetch would replay only the partial set → 401.
      if (shouldCache(url) && !this.__mffSelfFetch) {
        var self = this;
        // v0.9.53: capture query params (product, product_experience_id,
        // state_config_id) from UD's URL so we can replay them on our calls.
        try { _captureParamsFromUrl(url); } catch (_) {}
        // Stash this XHR's header set keyed by URL prefix (e.g., /v2/drafts/)
        // so a future request to /v2/drafts/<other-id> can use the same shape.
        try {
          var path = pathOf(url);
          // Use the path's first 2-3 segments as the prefix key
          var parts = path.split('/').filter(Boolean);
          var prefix = '/' + parts.slice(0, 2).join('/');
          // v0.9.54: only overwrite the captured set if the new one has at
          // least as many headers — avoids replacing a 11-header capture
          // with a sparse one (e.g., from a redirect).
          if (self.__mffHeaders) {
            var newCount = Object.keys(self.__mffHeaders).length;
            var existing = window.__mffUDHeaders[prefix];
            var existingCount = existing ? Object.keys(existing.headers).length : 0;
            if (!existing || newCount >= existingCount) {
              window.__mffUDHeaders[prefix] = {
                headers: Object.assign({}, self.__mffHeaders),
                ts: Date.now()
              };
            }
          }
        } catch (_) {}
        this.addEventListener('load', function () {
          try {
            if (self.status >= 200 && self.status < 300 && self.responseText) {
              var data = JSON.parse(self.responseText);
              var key = pathOf(url);
              writeCache(key, data, url);
              console.log('[MFF/inject] cached XHR response:', key, '(', self.responseText.length, 'bytes)');
            }
          } catch (e) { /* non-JSON response — ignore */ }
        });
      }
    } catch (_) {}
    return _xhrSend.apply(this, arguments);
  };

  // v0.9.54: Look up UD's headers. Tries the matching prefix first; if that
  // one is sparse (< 5 headers, likely a partial capture), falls through to
  // the BEST available header set across all prefixes (most headers wins).
  // This way a polluted /v2/drafts cache still gets fixed via /v1/teams's
  // 11-header capture.
  function lookupUDHeaders(url) {
    try {
      var path = pathOf(url);
      var parts = path.split('/').filter(Boolean);
      // Try most-specific prefix first
      for (var depth = Math.min(3, parts.length); depth >= 1; depth--) {
        var prefix = '/' + parts.slice(0, depth).join('/');
        var entry = window.__mffUDHeaders[prefix];
        if (entry && Object.keys(entry.headers).length >= 5) {
          return entry.headers;
        }
      }
      // Fall back to the most-complete captured set anywhere
      var best = null, bestCount = 0;
      for (var p in window.__mffUDHeaders) {
        var e = window.__mffUDHeaders[p];
        var c = Object.keys(e.headers).length;
        if (c > bestCount) { best = e.headers; bestCount = c; }
      }
      return best;
    } catch (_) {}
    return null;
  }

  // --- fetch wrap (kept for safety; Underdog uses XHR but who knows tomorrow) ---
  var _origFetch = window.fetch;
  window.fetch = function (input, init) {
    try {
      var url = typeof input === 'string' ? input : (input && input.url) || '';
      if (/^https?:\/\/api\.(underdogfantasy|underdogsports)\.com/.test(url)) {
        var headers = (init && init.headers) || (typeof input === 'object' && input && input.headers) || {};
        var auth = null;
        if (headers instanceof Headers) {
          auth = headers.get('Authorization') || headers.get('authorization');
        } else if (typeof headers === 'object') {
          auth = headers.Authorization || headers.authorization;
        }
        if (auth) captureToken(auth, 'fetch');
      }
    } catch (_) {}
    return _origFetch.apply(this, arguments);
  };

  // --- Sidebar → MAIN-world handler ---
  // Sidebar sends `mff-udsync-req`. We DON'T make a new API call; we
  // return whatever's in the cache. If the cache is empty, the sidebar's
  // error message tells the user to navigate to /active or /completed
  // first — that triggers Underdog's own fetch, which we snoop.
  window.addEventListener('message', function (ev) {
    if (!ev.data || ev.data.source !== 'mff-udsync-req') return;
    var reqId = ev.data.reqId;
    var endpoint = ev.data.endpoint;
    var path = pathOf(endpoint);
    var hit = window.__mffUDCache[path];
    if (!hit) {
      window.postMessage({
        source: 'mff-udsync-res',
        reqId: reqId,
        error: 'No cached response for ' + path + '. Navigate to your /active or /completed page on Underdog so the extension can snoop the response, then retry sync.'
      }, '*');
      return;
    }
    window.postMessage({
      source: 'mff-udsync-res',
      reqId: reqId,
      status: 200,
      data: hit.data,
      cachedAt: hit.ts
    }, '*');
  });

  // Also expose what's been cached for the sidebar to enumerate.
  window.addEventListener('message', function (ev) {
    if (!ev.data || ev.data.source !== 'mff-udsync-list') return;
    var paths = Object.keys(window.__mffUDCache).map(function (p) {
      return { path: p, ts: window.__mffUDCache[p].ts };
    });
    window.postMessage({ source: 'mff-udsync-list-res', reqId: ev.data.reqId, paths: paths }, '*');
  });

  // v0.9.26: bulk-fetch handler — return data for multiple cached paths
  // in one round trip. Sidebar uses this to grab every /v2/drafts/<id>
  // entry plus appearances/players for player-name resolution.
  window.addEventListener('message', function (ev) {
    if (!ev.data || ev.data.source !== 'mff-udsync-bulk') return;
    var reqId = ev.data.reqId;
    var prefixes = ev.data.prefixes || [];
    var matched = {};
    Object.keys(window.__mffUDCache).forEach(function (p) {
      for (var i = 0; i < prefixes.length; i++) {
        if (p.indexOf(prefixes[i]) === 0) {
          matched[p] = window.__mffUDCache[p].data;
          return;
        }
      }
    });
    window.postMessage({ source: 'mff-udsync-bulk-res', reqId: reqId, entries: matched }, '*');
  });

  // v0.9.29: hand the captured Bearer token to the sidebar so it can
  // forward it to the background worker for direct API calls.
  window.addEventListener('message', function (ev) {
    if (!ev.data || ev.data.source !== 'mff-udsync-token') return;
    window.postMessage({
      source: 'mff-udsync-token-res',
      reqId: ev.data.reqId,
      token: window.__mffUDAuth || null
    }, '*');
  });

  // v0.9.47/0.9.49: MAIN-world fetch via XMLHttpRequest. Earlier we used
  // `fetch()` here but it triggered "Failed to fetch / net::ERR_FAILED" on
  // api.underdogfantasy.com — the Content-Type: application/json header on
  // a GET request triggers a CORS preflight that UD's API doesn't accept.
  // UD's own SPA uses XHR (we see it in our snoop), so we mimic that exact
  // shape: XMLHttpRequest, withCredentials, only Authorization + Accept
  // headers, no Content-Type. Same JS path UD uses, so CORS behaves
  // identically and the call succeeds.
  window.addEventListener('message', function (ev) {
    if (!ev.data || ev.data.source !== 'mff-mainfetch') return;
    var reqId = ev.data.reqId;
    var url = ev.data.url;
    // v0.9.53: auto-append the required query params if missing. UD's API
    // 401s without them, regardless of how perfect the auth header is.
    url = _ensureParams(url);
    var path = pathOf(url);
    try {
      var xhr = new XMLHttpRequest();
      // v0.9.54: mark this XHR as our own so the wrapper above doesn't
      // capture our own minimal header set into __mffUDHeaders (would
      // pollute the cache with a 2-header replay set).
      xhr.__mffSelfFetch = true;
      xhr.open('GET', url, true);
      xhr.withCredentials = false;
      var udHdrs = lookupUDHeaders(url) || {};
      var setNames = {};
      // Replay every header UD's SPA used. Generate a FRESH Client-Request-Id
      // for this call (UD requires it to be unique per request — replaying
      // the captured one across many calls is asking for trouble).
      for (var k in udHdrs) {
        if (!udHdrs.hasOwnProperty(k)) continue;
        var v = udHdrs[k];
        if (k.toLowerCase() === 'client-request-id') {
          v = (window.crypto && crypto.randomUUID)
              ? crypto.randomUUID()
              : (Date.now() + '-' + Math.random().toString(36).slice(2));
        }
        try {
          xhr.setRequestHeader(k, v);
          setNames[k.toLowerCase()] = true;
        } catch (_) { /* some headers are forbidden — ignore */ }
      }
      // Backstops if no captured set existed (first ever call)
      if (!setNames['accept']) {
        try { xhr.setRequestHeader('Accept', 'application/json'); } catch (_) {}
      }
      if (!setNames['authorization'] && window.__mffUDAuth) {
        try { xhr.setRequestHeader('Authorization', window.__mffUDAuth); } catch (_) {}
      }
      xhr.timeout = 11000;
      xhr.onload = function () {
        try {
          if (xhr.status >= 200 && xhr.status < 300 && xhr.responseText) {
            var data = JSON.parse(xhr.responseText);
            // (Note: our own XHR wrap also caches this, but doing it here
            // explicitly guarantees the cache has it before we resolve.)
            try {
              writeCache(path, data, url);
            } catch (_) {}
            window.postMessage({
              source: 'mff-mainfetch-res',
              reqId: reqId,
              ok: true,
              status: xhr.status,
              data: data
            }, '*');
          } else {
            window.postMessage({
              source: 'mff-mainfetch-res',
              reqId: reqId,
              ok: false,
              status: xhr.status,
              body: (xhr.responseText || '').slice(0, 200)
            }, '*');
          }
        } catch (e) {
          window.postMessage({
            source: 'mff-mainfetch-res',
            reqId: reqId,
            ok: false,
            error: 'parse-err: ' + ((e && e.message) || String(e))
          }, '*');
        }
      };
      xhr.onerror = function () {
        window.postMessage({
          source: 'mff-mainfetch-res',
          reqId: reqId,
          ok: false,
          error: 'xhr-network-error'
        }, '*');
      };
      xhr.ontimeout = function () {
        window.postMessage({
          source: 'mff-mainfetch-res',
          reqId: reqId,
          ok: false,
          error: 'xhr-timeout'
        }, '*');
      };
      xhr.send();
    } catch (e) {
      window.postMessage({
        source: 'mff-mainfetch-res',
        reqId: reqId,
        ok: false,
        error: (e && e.message) || String(e)
      }, '*');
    }
  });

  // v0.10.40: mirror sync diag from sidebar (isolated world) into the page's
  // main world so it's readable from DevTools console as `window.__mffSyncDiag`.
  // Sidebar's own `window.__mffSyncDiag = _summary` sets the isolated-world
  // window, which the console can't see; postMessage is the CSP-safe bridge.
  window.addEventListener('message', function (ev) {
    if (!ev.data || ev.data.source !== 'mff-syncdiag') return;
    try { window.__mffSyncDiag = ev.data.summary; } catch (_) {}
  });

  console.log('[MFF/inject] passive XHR-snoop + main-world XHR fetch ready (v0.10.47, full UD headers + fresh request-id + query params + paginated-list merge)');
})();
