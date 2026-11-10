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

  // v0.18.19: API discovery log. Records the SHAPE (never headers/tokens) of
  // every JSON response Underdog's own app loads, one entry per endpoint
  // pattern, so we can find what the tournament leaderboard screen calls
  // (endpoint unknown — shouldCache below never matched it). Passive only:
  // nothing here issues a request. Read it from DevTools on the Underdog tab:
  //   copy(__mffApiLog())
  var PATHLOG_KEY = '__mffUDPathLog_v1';
  var PATHLOG_STD = ['product', 'product_experience_id', 'state_config_id'];
  var LB_RE = /(leaderboard|standing|rank|tournament_round)/i;
  window.__mffUDPathLog = (function () {
    try { return JSON.parse(sessionStorage.getItem(PATHLOG_KEY)) || {}; } catch (_) { return {}; }
  })();
  var _pathLogTimer = null;
  function savePathLog() {
    if (_pathLogTimer) return;
    _pathLogTimer = setTimeout(function () {
      _pathLogTimer = null;
      try { sessionStorage.setItem(PATHLOG_KEY, JSON.stringify(window.__mffUDPathLog)); } catch (_) {}
    }, 500);
  }
  function shapeOf(v, d) {
    if (v === null) return 'null';
    if (Array.isArray(v)) return '[' + v.length + ']' + (v.length && d > 0 ? ' of ' + JSON.stringify(shapeOf(v[0], d - 1)) : '');
    if (typeof v === 'object') {
      if (d <= 0) return '{..}';
      var o = {};
      Object.keys(v).slice(0, 40).forEach(function (k) { o[k] = shapeOf(v[k], d - 1); });
      return o;
    }
    return typeof v;
  }
  function logApi(url, status, text, via) {
    try {
      var u = new URL(url, location.href);
      if (!UD_HOST_RE.test(u.hostname)) return;
      if (!text || (text.charAt(0) !== '{' && text.charAt(0) !== '[')) return;
      var norm = u.pathname
        .replace(/[0-9a-f]{8}-[0-9a-f-]{27,}/gi, '<id>')
        .replace(/\/\d+(?=\/|$)/g, '/<n>');
      var qs = [];
      u.searchParams.forEach(function (v, k) { if (PATHLOG_STD.indexOf(k) < 0) qs.push(k + '=' + v); });
      var isLb = LB_RE.test(norm);
      var e = window.__mffUDPathLog[norm] || (window.__mffUDPathLog[norm] = { n: 0 });
      e.n++; e.via = via; e.host = u.hostname; e.last = u.pathname; e.qs = qs.join('&');
      e.status = status; e.bytes = text.length; e.ts = Date.now();
      if (e.n <= 3 || isLb) e.shape = shapeOf(JSON.parse(text), 4);
      if (isLb) {
        e.sample = text.slice(0, 1500);
        if (e.n === 1) console.log('[MFF/inject] leaderboard-like endpoint:', u.pathname + u.search);
      }
      savePathLog();
    } catch (_) {}
  }
  window.__mffApiLog = function () { return JSON.stringify(window.__mffUDPathLog, null, 1); };

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
      // v0.18.19: discovery log for every UD JSON response (see logApi).
      if (url && !this.__mffSelfFetch) {
        var lx = this;
        this.addEventListener('load', function () {
          try {
            var txt = (lx.responseType === '' || lx.responseType === 'text') ? lx.responseText
                    : (lx.responseType === 'json' && lx.response ? JSON.stringify(lx.response) : '');
            logApi(url, lx.status, txt, 'xhr');
          } catch (_) {}
        });
      }
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
    var p = _origFetch.apply(this, arguments);
    // v0.18.19: discovery log (JSON responses only; the page's own promise
    // is returned untouched).
    try {
      if (url && UD_HOST_RE.test(url)) {
        p.then(function (res) {
          try {
            if (!/json/i.test(res.headers.get('content-type') || '')) return;
            res.clone().text().then(function (t) { logApi(url, res.status, t, 'fetch'); }).catch(function () {});
          } catch (_) {}
        }).catch(function () {});
      }
    } catch (_) {}
    return p;
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

  // ==========================================================================
  // v0.18.20: OVERALL-LEADERBOARD PULL (Sim Lab "overall standings" input).
  // Jack asked for this explicitly (10-01): one full pull so every exact team
  // is in the sim, points refreshed weekly from stats afterwards.
  //
  // /v1/tournament_rounds/<round>/leaderboard?page=N returns 50 entries per
  // page — place, points, regular-season payout AND each entry's 18
  // appearance ids (its roster). BBM VII is ~13,450 pages, so the full pull
  // is ~13,600 requests, one at a time, `delayMs` apart (~3 hours). Runs ONLY
  // from the Settings button (or __mffPullLeaderboard()); nothing here fires
  // on its own, and it stops on the first auth error or repeated failure.
  //
  // Page order keeps a stopped pull usable: every page through the paid
  // places first, then the rest in 32 evenly spread passes — so at any point
  // the pages in hand are a uniform sample, and each page's weight (how many
  // leaderboard pages it stands for) is just its gap to its neighbours.
  // A finished pull has every weight = 1. Pressing the button again in the
  // same tab continues where a stopped pull left off.
  //
  // Output: a downloaded mff_bbm_leaderboard_<stamp>.json
  //   { kind:'mff_ud_leaderboard', v:3, pulledAt, round, tournament, me,
  //     total, perPage, lastPage, complete, pages:[[page, weight]...],
  //     apps:[[name, pos, seasonPts]...],             // appearance dictionary
  //     entries:[[page, place, points, payout, username, [appIdx x18], pod]...],
  //     mine:[{draftId, entryId, title, points, podPlace, payoutText, apps, pod}],
  //     nPods }
  // v3 (0.18.22): `pod` = an index standing for the entry's draft id — which
  // 12 teams drafted together. The Round-1 advance (top 2 of each draft) and
  // so the whole playoff sim hang on it; v2 files don't carry it.
  //
  // QUICK MODE (0.18.23), opts.mode = 'mypods': only the user's OWN drafts —
  // the drafts list plus one /v2/drafts/<id> each (~150 requests, a couple of
  // minutes), no leaderboard pages. Saves mff_bbm_mypods_<stamp>.json, kind
  // 'mff_ud_mypods': mine[] as above plus `podRosters` = all 12 rosters of
  // that draft. Sim Lab lays those real draft groups over a field file that
  // has none, which makes the user's own advance / playoff odds exact without
  // pulling 13,000 pages again.
  // ==========================================================================
  var LB_API = 'https://api.underdogfantasy.com';
  var LB_STATS = 'https://stats.underdogfantasy.com';
  var LB_PASSES = [0, 16, 8, 24, 4, 20, 12, 28, 2, 18, 10, 26, 6, 22, 14, 30,
                   1, 17, 9, 25, 5, 21, 13, 29, 3, 19, 11, 27, 7, 23, 15, 31];
  var _lb = { running: false, stop: false, st: null };

  // Promise GET with the same header replay as the mff-mainfetch handler.
  function udGet(url, timeoutMs) {
    return new Promise(function (resolve) {
      url = _ensureParams(url);
      try {
        var xhr = new XMLHttpRequest();
        xhr.__mffSelfFetch = true;
        xhr.open('GET', url, true);
        xhr.withCredentials = false;
        var udHdrs = lookupUDHeaders(url) || {};
        var setNames = {};
        for (var k in udHdrs) {
          if (!udHdrs.hasOwnProperty(k)) continue;
          var v = udHdrs[k];
          if (k.toLowerCase() === 'client-request-id') {
            v = (window.crypto && crypto.randomUUID)
                ? crypto.randomUUID()
                : (Date.now() + '-' + Math.random().toString(36).slice(2));
          }
          try { xhr.setRequestHeader(k, v); setNames[k.toLowerCase()] = true; } catch (_) {}
        }
        if (!setNames['accept']) { try { xhr.setRequestHeader('Accept', 'application/json'); } catch (_) {} }
        if (!setNames['authorization'] && window.__mffUDAuth) {
          try { xhr.setRequestHeader('Authorization', window.__mffUDAuth); } catch (_) {}
        }
        xhr.timeout = timeoutMs || 20000;
        xhr.onload = function () {
          try {
            if (xhr.status >= 200 && xhr.status < 300 && xhr.responseText) {
              resolve({ ok: true, status: xhr.status, data: JSON.parse(xhr.responseText) });
            } else {
              resolve({ ok: false, status: xhr.status, body: (xhr.responseText || '').slice(0, 200) });
            }
          } catch (e) { resolve({ ok: false, error: 'parse-err: ' + ((e && e.message) || e) }); }
        };
        xhr.onerror = function () { resolve({ ok: false, error: 'xhr-network-error' }); };
        xhr.ontimeout = function () { resolve({ ok: false, error: 'xhr-timeout' }); };
        xhr.send();
      } catch (e) { resolve({ ok: false, error: (e && e.message) || String(e) }); }
    });
  }
  // Pacing delay. A hidden tab's own timers get throttled to as little as
  // one per minute, which would stretch a 3-hour pull into days — so the
  // sidebar also relays the wait to the background worker (not throttled)
  // and whichever fires first ends the sleep. Neither can fire early.
  var _lbSleepId = 0;
  function lbSleep(ms) {
    return new Promise(function (resolve) {
      var id = ++_lbSleepId, done = false;
      function fin() {
        if (done) return;
        done = true;
        window.removeEventListener('message', onMsg);
        resolve();
      }
      function onMsg(ev) { if (ev.data && ev.data.source === 'mff-lb-wake' && ev.data.id === id) fin(); }
      window.addEventListener('message', onMsg);
      setTimeout(fin, ms);
      try { window.postMessage({ source: 'mff-lb-sleep', id: id, ms: ms }, '*'); } catch (_) {}
    });
  }
  function lbStatus(text, extra) {
    var msg = { source: 'mff-lbpull-status', text: text, running: _lb.running };
    if (extra) for (var k in extra) msg[k] = extra[k];
    try { window.postMessage(msg, '*'); } catch (_) {}
    console.log('[MFF/leaderboard] ' + text);
  }
  // One request at a time, `delayMs` apart. Auth errors abort at once;
  // timeouts / 408 / 429 / 5xx back off and retry twice, then abort.
  async function lbGet(url, o) {
    for (var attempt = 0; attempt < 3; attempt++) {
      if (_lb.stop) throw new Error('stopped');
      await lbSleep(attempt ? 10000 * attempt : o.delayMs);
      var r = await udGet(url, 25000);
      if (r.ok) return r.data;
      if (r.status === 401 || r.status === 403) throw new Error('Underdog returned ' + r.status + ' (signed out?) — refresh the tab and press the button again');
      if (r.status && r.status !== 408 && r.status !== 429 && r.status < 500) throw new Error('HTTP ' + r.status + ' for ' + pathOf(url));
      console.warn('[MFF/leaderboard] retry', attempt + 1, pathOf(url), r.status || r.error);
    }
    throw new Error('gave up on ' + pathOf(url) + ' after 3 tries');
  }
  function lbCached(re) {
    var keys = Object.keys(window.__mffUDCache);
    for (var i = 0; i < keys.length; i++) {
      if (re.test(keys[i]) && window.__mffUDCache[keys[i]] && window.__mffUDCache[keys[i]].data) return window.__mffUDCache[keys[i]].data;
    }
    return null;
  }

  async function lbFindRound(o) {
    var rounds = [], seen = {};
    function take(list) {
      (list || []).forEach(function (r) {
        if (r && r.id && !seen[r.id]) { seen[r.id] = 1; rounds.push(r); }
      });
    }
    Object.keys(window.__mffUDCache).forEach(function (k) {
      if (/^\/v1\/user\/slates\/[^/]+\/tournament_rounds$/.test(k)) take((window.__mffUDCache[k].data || {}).tournament_rounds);
    });
    function pick() {
      var c = rounds.filter(function (r) {
        return r.leaderboard_enabled && r.tournament && o.title.test(r.tournament.title || '');
      }).sort(function (a, b) { return (a.number || 0) - (b.number || 0); });
      return c[0] || null;
    }
    var hit = pick();
    if (hit) return hit;
    lbStatus('Looking up live tournaments…');
    var live = await lbGet(LB_API + '/v2/user/sports/nfl/live_slates?best_ball=true', o);
    var slates = (live && live.slates) || [];
    for (var i = 0; i < slates.length; i++) {
      var tr = await lbGet(LB_API + '/v1/user/slates/' + slates[i].id + '/tournament_rounds', o);
      take(tr && tr.tournament_rounds);
      hit = pick();
      if (hit) return hit;
    }
    var withLb = rounds.filter(function (r) { return r.leaderboard_enabled; })
      .map(function (r) { return (r.tournament && r.tournament.title) || r.title; });
    throw new Error('No live tournament round with a leaderboard matched ' + o.title +
      (withLb.length ? ' (leaderboards exist for: ' + withLb.join(', ') + ')' : ''));
  }

  // appearance id -> [name, pos, seasonPts] for the round's slate.
  async function lbAppearanceMap(round, o) {
    var slate = round.slate_id;
    var esc = String(slate).replace(/[^a-f0-9-]/gi, '');
    var apps = lbCached(new RegExp('^/v1/slates/' + esc + '/scoring_types/[^/]+/appearances$'));
    var players = lbCached(new RegExp('^/v[12]/slates/' + esc + '/players$'));
    if (!players) {
      lbStatus('Loading the player list…');
      players = await lbGet(LB_STATS + '/v1/slates/' + slate + '/players', o);
    }
    if (!apps) {
      lbStatus('Loading player appearances…');
      var styles = await lbGet(LB_STATS + '/v1/contest_styles', o);
      var csId = round.tournament && round.tournament.contest_style_id;
      var cs = ((styles && styles.contest_styles) || []).filter(function (c) { return c.id === csId; })[0];
      if (!cs || !cs.scoring_type_id) throw new Error('could not resolve the scoring type for this contest');
      apps = await lbGet(LB_STATS + '/v1/slates/' + slate + '/scoring_types/' + cs.scoring_type_id + '/appearances', o);
    }
    var pById = {};
    ((players && players.players) || []).forEach(function (p) { pById[p.id] = p; });
    var map = {}, n = 0;
    ((apps && apps.appearances) || []).forEach(function (a) {
      var p = pById[a.player_id];
      if (!p) return;
      var name = ((p.first_name || '') + ' ' + (p.last_name || '')).trim();
      var pts = a.score && a.score.points != null ? +a.score.points : null;
      map[a.id] = [name, p.position_name || p.position_display_name || '', pts];
      n++;
    });
    if (!n) throw new Error('player list came back empty');
    return map;
  }

  // Weights from whatever pages are in hand: each page stands for the
  // leaderboard pages nearer to it than to any other pulled page.
  function lbPageWeights(st) {
    var pgs = Object.keys(st.got).map(Number).sort(function (a, b) { return a - b; });
    var L = st.out.lastPage || pgs[pgs.length - 1];
    return pgs.map(function (p, i) {
      var lo = i === 0 ? 0.5 : (pgs[i - 1] + p) / 2;
      var hi = i === pgs.length - 1 ? L + 0.5 : (p + pgs[i + 1]) / 2;
      return [p, +(hi - lo).toFixed(3)];
    });
  }

  async function lbPull(opts) {
    if (_lb.running) { lbStatus('Already running.'); return null; }
    var o = { title: /best ball mania/i, delayMs: 450, minDense: 100, maxDense: 300 };
    if (opts) for (var k in opts) o[k] = opts[k];
    _lb.running = true; _lb.stop = false;
    var quick = o.mode === 'mypods';
    var st = quick ? null : _lb.st, t0 = Date.now(), reqs = 0, err = null;
    try {
      var round = await lbFindRound(o);
      var tName = (round.tournament && round.tournament.title) || round.title || 'tournament';
      // continue a stopped pull of the same round (same tab, under 12h old)
      if (!st || st.roundId !== round.id || st.out.complete || Date.now() - st.startedAt > 12 * 3600000) {
        var meUser = (lbCached(/^\/v1\/user$/) || {}).user || {};
        st = {
          roundId: round.id, startedAt: Date.now(), got: {}, denseEnd: 0, appIx: {}, mineDone: false,
          podIx: {}, nPods: 0,
          appMap: await lbAppearanceMap(round, o),
          out: {
            kind: quick ? 'mff_ud_mypods' : 'mff_ud_leaderboard', v: 3, pulledAt: new Date().toISOString(),
            round: { id: round.id, title: round.title, number: round.number, description: round.description },
            tournament: { id: round.tournament && round.tournament.id, title: tName,
                          entry_count: round.tournament && round.tournament.entry_count },
            me: { userId: meUser.id || null, username: meUser.username || null },
            total: null, perPage: null, lastPage: null, complete: false,
            pages: [], apps: [], entries: [], mine: []
          }
        };
        if (quick) _lb.quick = st; else _lb.st = st; // a quick pull never disturbs a full pull in progress
      } else {
        lbStatus(tName + ': continuing — ' + Object.keys(st.got).length + ' pages already in hand.');
      }
      var out = st.out;
      window.__mffLbExport = out;
      var ix = function (id) {
        if (st.appIx[id] !== undefined) return st.appIx[id];
        st.appIx[id] = out.apps.length;
        out.apps.push(st.appMap[id] || ['?' + id, '', null]);
        return st.appIx[id];
      };
      var podOf = function (draftId) { // draft id -> small int (-1 = none)
        if (!draftId) return -1;
        if (st.podIx[draftId] === undefined) st.podIx[draftId] = st.nPods++;
        return st.podIx[draftId];
      };

      // --- my entries: list (points / pod place), then each draft's picks ---
      if (!st.mineDone) {
        var myDrafts = [];
        for (var pg = 1; pg && pg < 200; ) {
          var dl = await lbGet(LB_API + '/v1/user/tournament_rounds/' + round.id + '/drafts?page=' + pg, o);
          reqs++;
          myDrafts = myDrafts.concat((dl && dl.drafts) || []);
          pg = dl && dl.meta && dl.meta.next ? dl.meta.next : 0;
          lbStatus(tName + ': found ' + myDrafts.length + ' of your entries…');
        }
        out.mine = [];
        for (var d = 0; d < myDrafts.length; d++) {
          var md = myDrafts[d];
          var hit = window.__mffUDCache['/v2/drafts/' + md.id];
          var dd = hit && hit.data;
          if (!dd) { dd = await lbGet(LB_API + '/v2/drafts/' + md.id, o); reqs++; }
          var allPicks = (dd && dd.draft && dd.draft.picks) || [];
          var picks = allPicks.filter(function (p) {
            return p.draft_entry_id === md.user_draft_entry_id;
          });
          // every roster of this draft (mine included), for the quick mode
          var byEntry = {}, podRosters = [];
          allPicks.forEach(function (p) {
            if (!byEntry[p.draft_entry_id]) podRosters.push(byEntry[p.draft_entry_id] = []);
            byEntry[p.draft_entry_id].push(ix(p.appearance_id));
          });
          out.mine.push({
            podRosters: quick ? podRosters : undefined,
            draftId: md.id, entryId: md.user_draft_entry_id, title: md.title || null,
            points: +md.user_draft_entry_points || 0, podPlace: md.user_draft_entry_place || null,
            payoutText: md.user_draft_entry_payout_text || null,
            apps: picks.map(function (p) { return ix(p.appearance_id); }), pod: podOf(md.id)
          });
          if (d % 5 === 4 || d === myDrafts.length - 1) lbStatus(tName + ': your rosters ' + (d + 1) + '/' + myDrafts.length);
        }
        st.mineDone = true;
      }
      if (quick) { out.complete = true; throw { quickDone: true }; }

      // --- leaderboard pages ---
      var base = LB_API + '/v1/tournament_rounds/' + round.id + '/leaderboard?page=';
      var nGot = Object.keys(st.got).length, tPages = Date.now(), nThisRun = 0;
      var getPage = async function (page) {
        var data = await lbGet(base + page, o);
        reqs++; nThisRun++;
        var list = (data && data.tournament_round_entries) || [];
        st.got[page] = 1; nGot++;
        for (var i = 0; i < list.length; i++) {
          var e = list[i];
          out.entries.push([page, e.place, +e.points || 0, +e.payout || 0,
            e.username || (e.user && e.user.username) || '', (e.appearance_ids || []).map(ix), podOf(e.draft_id)]);
        }
        if (page === 1 && !out.lastPage) {
          out.perPage = list.length || 50;
          var cnt = data && data.meta && +data.meta.count, ec = +out.tournament.entry_count || 0;
          // meta.count is the entry total on the list endpoints seen so far;
          // if it ever turns out to be a page count, entry_count catches it.
          out.total = (cnt && ec && Math.abs(cnt - ec) > ec * 0.05 &&
                       Math.abs(cnt * out.perPage - ec) < ec * 0.05) ? ec : (cnt || ec || null);
          out.lastPage = out.total ? Math.ceil(out.total / out.perPage) : null;
        }
        if (nThisRun % 10 === 0 || page === 1) {
          var left = out.lastPage ? out.lastPage - nGot : 0;
          var per = (Date.now() - tPages) / nThisRun;
          lbStatus(tName + ': ' + nGot + (out.lastPage ? ' of ' + out.lastPage : '') + ' leaderboard pages · ' +
            out.entries.length.toLocaleString() + ' teams' +
            (left > 0 ? ' · about ' + Math.max(1, Math.round(left * per / 60000)) + ' min left' : '') +
            ' — press again to stop and save what is pulled');
        }
        return { list: list, next: data && data.meta && data.meta.next };
      };
      // dense: every page until the leaderboard's payouts reach $0
      while (!st.denseDone) {
        var page = st.denseEnd + 1;
        var r = st.got[page] ? null : await getPage(page);
        st.denseEnd = page;
        if (!r) continue;
        var lastPay = r.list.length ? (+r.list[r.list.length - 1].payout || 0) : 0;
        if (!r.list.length || !r.next || (out.lastPage && page >= out.lastPage) ||
            (page >= o.minDense && lastPay <= 0) || page >= o.maxDense) st.denseDone = true;
      }
      // the rest, in 32 evenly spread passes
      if (out.lastPage) {
        for (var ps = 0; ps < LB_PASSES.length; ps++) {
          for (var p2 = st.denseEnd + 1 + LB_PASSES[ps]; p2 <= out.lastPage; p2 += 32) {
            if (!st.got[p2]) await getPage(p2);
          }
        }
        out.complete = nGot >= out.lastPage;
      }
    } catch (e) {
      err = (e && e.quickDone) ? null : ((e && e.message) || String(e));
    }
    _lb.running = false;
    var o2 = st && st.out;
    if (quick) {
      if (o2 && o2.mine.length && !err) {
        var qname = lbSave(st);
        lbStatus('Done — your ' + o2.mine.length + ' draft groups (' + reqs + ' requests in ' + Math.round((Date.now() - t0) / 1000) +
          's) → ' + qname + ' in Downloads. Load it in Sim Lab → BEST BALL → OVERALL STANDINGS, same file box.', { done: true });
      } else {
        lbStatus('Nothing saved' + (err ? ': ' + err : '.'), { done: true });
      }
      return o2 || null;
    }
    if (o2 && o2.entries.length && o2.mine.length) {
      var fname = lbSave();
      lbStatus((o2.complete ? 'Done — the whole field: ' : (err === 'stopped' ? 'Stopped — ' : 'Stopped (' + err + ') — ')) +
        o2.entries.length.toLocaleString() + ' teams + ' + o2.mine.length + ' of yours, ' + reqs + ' requests in ' +
        Math.round((Date.now() - t0) / 60000) + ' min → ' + fname + ' in Downloads. Load it in Sim Lab → BEST BALL → OVERALL STANDINGS.' +
        (o2.complete ? '' : ' Press the button again to continue from here.'), { done: true });
    } else {
      lbStatus('Nothing saved' + (err ? ': ' + err : '.'), { done: true });
    }
    return o2 || null;
  }
  function lbSave(which) {
    var st = which || _lb.st;
    if (!st || !st.out) return null;
    var out = st.out, quick = out.kind === 'mff_ud_mypods';
    if (!quick) { out.pages = lbPageWeights(st); out.nPods = st.nPods; }
    var fname = (quick ? 'mff_bbm_mypods_' : 'mff_bbm_leaderboard_') + out.pulledAt.replace(/[-:]/g, '').replace('T', '_').slice(0, 13) +
      (out.complete ? '' : '_partial') + '.json';
    var a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([JSON.stringify(out)], { type: 'application/json' }));
    a.download = fname;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { try { URL.revokeObjectURL(a.href); } catch (_) {} }, 120000);
    return fname;
  }
  window.__mffPullLeaderboard = lbPull;
  window.__mffStopLeaderboard = function () { _lb.stop = true; };
  window.__mffSaveLeaderboard = lbSave;
  window.addEventListener('message', function (ev) {
    if (!ev.data || ev.data.source !== 'mff-lbpull') return;
    if (ev.data.cmd === 'stop') { _lb.stop = true; return; }
    if (ev.data.cmd === 'start') lbPull(ev.data.mode === 'mypods' ? { mode: 'mypods' } : null);
  });

  console.log('[MFF/inject] passive XHR-snoop + main-world XHR fetch ready (v0.18.23, full UD headers + fresh request-id + query params + paginated-list merge + API discovery log + leaderboard pull)');
})();
