// MFF Sleeper Draft Helper — background service worker.
// 1) Fetch proxy for content scripts (they inherit page CORS).
// 2) Slow-draft watcher: polls tracked drafts once a minute via chrome.alarms
//    and fires a desktop notification when your pick is <= 1 away — works
//    with the Sleeper tab closed.

const ALLOWED_PREFIXES = [
  'https://api.sleeper.app/',
  'https://firestore.googleapis.com/v1/projects/jackb933-website/',
  'https://myfantasyfootball.co/data/',       // live Vegas JSON (v0.10.4)
  'https://www.myfantasyfootball.co/data/',   // canonical www host (v0.10.5)
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
  if (msg && msg.type === 'mffWatch') {
    ensureAlarm();
    checkDrafts();
    sendResponse({ ok: true });
    return false;
  }
});

// ---------- slow-draft watcher ----------
const ALARM = 'mffDraftWatch';
function ensureAlarm() {
  chrome.alarms.create(ALARM, { periodInMinutes: 1 });
}
chrome.runtime.onInstalled.addListener(ensureAlarm);
chrome.runtime.onStartup.addListener(ensureAlarm);
chrome.alarms.onAlarm.addListener((a) => {
  if (a.name === ALARM) checkDrafts();
});

// Same snake/linear/3RR math as the sidebar.
function slotForPick(pickNo, meta) {
  const t = meta.teams;
  const round = Math.ceil(pickNo / t);
  const idx = (pickNo - 1) % t;
  if (meta.type === 'linear') return idx + 1;
  const rev = meta.reversal_round || 0;
  let forward = round % 2 === 1;
  if (rev > 0 && round >= rev) forward = !forward;
  return forward ? idx + 1 : t - idx;
}

async function checkDrafts() {
  const all = await chrome.storage.local.get(null);
  for (const [key, prefs] of Object.entries(all)) {
    if (!key.startsWith('sleeperDraft_')) continue;
    if (!prefs || !prefs.tracking || prefs.notify === false || !prefs.slot || !prefs.meta || prefs.done) continue;
    const draftId = key.slice('sleeperDraft_'.length);
    try {
      const picks = await (await fetch('https://api.sleeper.app/v1/draft/' + draftId + '/picks')).json();
      if (!Array.isArray(picks)) continue;
      const meta = prefs.meta;
      const total = meta.teams * meta.rounds;
      if (picks.length >= total) {
        prefs.done = true;
        await chrome.storage.local.set({ [key]: prefs });
        continue;
      }
      const next = picks.length + 1;
      let until = null;
      for (let p = next; p <= total; p++) {
        if (slotForPick(p, meta) === prefs.slot) { until = p - next; break; }
      }
      if (until == null || until > 1) continue;
      const stateKey = picks.length + ':' + until;
      if (prefs.lastNotify === stateKey) continue;
      prefs.lastNotify = stateKey;
      await chrome.storage.local.set({ [key]: prefs });
      const rd = Math.ceil(next / meta.teams);
      const rdPick = ((next - 1) % meta.teams) + 1;
      chrome.notifications.create('mff_' + draftId, {
        type: 'basic',
        iconUrl: 'icons/icon-128.png',
        title: until === 0 ? "🏈 You're ON THE CLOCK" : '🏈 1 pick until you',
        message: (meta.name || 'Sleeper draft') + ' — pick ' + rd + '.' + String(rdPick).padStart(2, '0') + ' (#' + next + ')',
        priority: 2,
      });
    } catch (e) { /* transient network errors — next tick retries */ }
  }
}

chrome.notifications.onClicked.addListener((nid) => {
  if (nid.startsWith('mff_')) {
    chrome.tabs.create({ url: 'https://sleeper.com/draft/nfl/' + nid.slice(4) });
    chrome.notifications.clear(nid);
  }
});
