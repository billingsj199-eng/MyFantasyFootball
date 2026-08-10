/* MFF Underdog Draft Helper — background service worker (MV3)
 *
 * v0.9.30: improved diagnostics (logs response body on failure) and
 * tries multiple auth combinations:
 *   1. Bearer token + credentials:'include' (cookies should flow)
 *   2. If 401, try with explicit cookies from chrome.cookies API
 */

// v0.10.1: dual-domain — UD is migrating from underdogfantasy.com to
// underdogsports.com. Pick the right Origin/Referer/cookie domain based on
// the API host we're hitting so this works on either side of the migration.
function _udFamilyForUrl(url) {
  try {
    const h = new URL(url).hostname;
    if (/underdogsports\.com$/.test(h)) return 'underdogsports.com';
  } catch (_) {}
  return 'underdogfantasy.com';
}

async function getCookieHeader(url) {
  try {
    // v0.10.1: try the host that matches the URL first, then fall back to
    // the other UD domain (cookies may be set on either during the migration).
    const primary = _udFamilyForUrl(url);
    const secondary = primary === 'underdogfantasy.com' ? 'underdogsports.com' : 'underdogfantasy.com';
    const seen = new Set();
    const merged = [];
    for (const dom of [primary, secondary]) {
      const cookies = await chrome.cookies.getAll({ domain: dom });
      if (!cookies) continue;
      for (const c of cookies) {
        if (seen.has(c.name)) continue;
        seen.add(c.name);
        merged.push(c.name + '=' + c.value);
      }
    }
    return merged.length ? merged.join('; ') : null;
  } catch (e) {
    console.warn('[MFF/bg] could not read cookies:', e);
    return null;
  }
}

async function doFetch(url, token, useExplicitCookies) {
  const family = _udFamilyForUrl(url);
  const appOrigin = 'https://app.' + family;
  const headers = {
    'Accept': 'application/json',
    'Authorization': token,
    'Origin': appOrigin
  };
  if (useExplicitCookies) {
    const cookieHeader = await getCookieHeader(url);
    if (cookieHeader) headers['Cookie'] = cookieHeader;
  }
  const resp = await fetch(url, {
    method: 'GET',
    headers,
    credentials: 'include',
    referrer: appOrigin + '/'
  });
  const text = await resp.text();
  let data = null;
  try { data = JSON.parse(text); } catch (_) {}
  return { ok: resp.ok, status: resp.status, data, body: text.slice(0, 600) };
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || msg.type !== 'mff-bg-fetch') return false;

  (async () => {
    try {
      // First attempt: standard credentials:'include'
      let res = await doFetch(msg.url, msg.token, false);
      if (res.status === 401) {
        // Retry with explicit cookies (in case credentials:'include'
        // wasn't pulling them in service worker context)
        console.log('[MFF/bg] 401 on first attempt, retrying with explicit cookies for', msg.url);
        res = await doFetch(msg.url, msg.token, true);
        res.retried = true;
      }
      sendResponse(res);
    } catch (err) {
      console.warn('[MFF/bg] fetch error:', err);
      sendResponse({ ok: false, error: err.message || String(err) });
    }
  })();
  return true;
});

console.log('[MFF/bg] background worker ready (v0.15.1)');

// --- Live Vegas refresh (v0.10.52) -----------------------------------------
// Plain fetch of the site's machine-readable betting lines JSON (written by
// pull_betting_lines.py, deployed on GitHub Pages). sidebar.js overlays the
// gameTotals onto the bundled MFF_PLAYOFF_SOS so bringback/SOS numbers stay
// current without re-exporting the extension. No auth, no cookies.
// www is the canonical host — the apex 301s to it; fetch it directly.
const MFF_VEGAS_URL = 'https://www.myfantasyfootball.co/data/betting_lines_2026.json';
// v0.10.59: site-hosted UD ADP history (written daily by the site's 9 AM
// consensus-ADP task from the shared/ud_adp_latest Firestore mirror).
// sidebar.js merges it into local mff_adp_history so ADP-movement arrows
// have a complete multi-day baseline even on machines that skipped days.
const MFF_ADP_HISTORY_URL = 'https://www.myfantasyfootball.co/data/ud_adp_history.json';
// v0.15.1: live Jack's boards straight from Firestore (same public REST doc
// the Sleeper/ESPN/Yahoo helpers read — sends CORS *, no auth). Lets a saved
// board on the site reach the Underdog sidebar on next page load WITHOUT
// requiring a site visit to run the bridge first.
const MFF_JACKS_URL =
  'https://firestore.googleapis.com/v1/projects/jackb933-website/databases/(default)' +
  '/documents/rankings/jacks-official?key=AIzaSyD9D_Rhb5hEpz2cBWqQr7hcFCDoluwq6uY';
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg) return false;
  const url = msg.type === 'mff-vegas-fetch' ? MFF_VEGAS_URL
            : msg.type === 'mff-adp-history-fetch' ? MFF_ADP_HISTORY_URL
            : msg.type === 'mff-jacks-fetch' ? MFF_JACKS_URL
            : null;
  if (!url) return false;
  // Cache-bust the GitHub-Pages JSON only — Firestore REST sends no-cache
  // headers itself and Google APIs can 400 on unexpected query params.
  fetch(url + (url.indexOf('?') >= 0 ? '' : '?t=' + Date.now()), { headers: { 'Accept': 'application/json' } })
    .then((r) => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then((data) => sendResponse({ ok: true, data }))
    .catch((e) => sendResponse({ ok: false, error: String(e) }));
  return true;
});
