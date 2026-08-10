// MFF Yahoo Helper — background service worker: JSON fetch proxy for content
// scripts. Yahoo's page CSP can block cross-origin fetches from content
// scripts, so sidebar.js tries a direct fetch first and relays through here
// when that throws. Allow-list mirrors the Sleeper/ESPN helpers'.
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
