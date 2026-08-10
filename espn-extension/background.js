// MFF ESPN Helper — background service worker: JSON fetch proxy for content
// scripts. ESPN's page CSP currently allows cross-origin fetches from content
// scripts (the sidebar fetches Firestore + the site JSON directly), so this
// is the FALLBACK path only — fetchJson() in sidebar.js relays through here
// when a direct fetch throws. Allow-list mirrors the Sleeper helper's.
const ALLOWED_PREFIXES = [
  'https://api.sleeper.app/',
  'https://firestore.googleapis.com/v1/projects/jackb933-website/',
  'https://myfantasyfootball.co/data/',
  'https://www.myfantasyfootball.co/data/',
];

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg && msg.type === 'mffFetch' && typeof msg.url === 'string' &&
      ALLOWED_PREFIXES.some((p) => msg.url.startsWith(p))) {
    fetch(msg.url)
      .then((r) => {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then((data) => sendResponse({ ok: true, data }))
      .catch((e) => sendResponse({ ok: false, error: String(e) }));
    return true; // async sendResponse
  }
});
