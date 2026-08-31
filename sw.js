/* MyFantasyFootball service worker.
   Strategy:
   - HTML navigations  → network-first with a short timeout, cached shell as the fallback.
     This was stale-while-revalidate until 2026-08-18: it served the cached shell instantly
     and only picked the new deploy up on the NEXT load, so every returning visitor ran one
     version behind and a fresh deploy looked like it simply hadn't shipped. This site deploys
     several times a day, so shipping correctly beats the ~330–440ms SWR bought on repeat
     loads. NAV_TIMEOUT_MS bounds the cost: a slow or dead network falls back to the cached
     shell instead of hanging, so offline still works.
   - Versioned static assets (/styles/*.css?v=…, /data/*.js?v=…) → cache-first (URL changes when content does).
   - Unversioned same-origin GETs and Google Fonts woff2 / ESPN images → stale-while-revalidate.
   - Firebase / ESPN / Sleeper / Cloudflare APIs → bypass entirely.
   Bump SW_VERSION when changing SW logic so old caches get wiped on activate. */

const SW_VERSION   = '2026-08-31a';
// How long a navigation waits for the network before falling back to the cached
// shell. Long enough to win on any normal connection, short enough that a dead
// one doesn't feel broken.
const NAV_TIMEOUT_MS = 1500;
const SHELL_CACHE  = 'mff-shell-' + SW_VERSION;
const STATIC_CACHE = 'mff-static-' + SW_VERSION;
const RUNTIME_CACHE = 'mff-runtime-' + SW_VERSION;

// Precache only the navigation shell. Versioned assets are picked up organically
// via SWR/cache-first on first fetch — keeps the SW decoupled from CSS/data versions.
const PRECACHE = [
  '/',
  '/index.html',
  '/manifest.webmanifest',
];

// Hosts we never intercept — auth, realtime DB, third-party APIs.
const BYPASS_HOSTS = [
  'firestore.googleapis.com',
  'identitytoolkit.googleapis.com',
  'securetoken.googleapis.com',
  'firebaseio.com',
  'firebaseapp.com',
  'site.api.espn.com',
  'sports.core.api.espn.com',
  'api.sleeper.app',
  'cloudfunctions.net',
  'run.app',
  'workers.dev',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE)
      .then((c) => c.addAll(PRECACHE))
      .catch(() => { /* best-effort */ })
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  const keep = new Set([SHELL_CACHE, STATIC_CACHE, RUNTIME_CACHE]);
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => !keep.has(k)).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('message', (event) => {
  if (event.data === 'SKIP_WAITING') self.skipWaiting();
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);

  if (BYPASS_HOSTS.some((h) => url.hostname.endsWith(h))) return;

  // HTML navigations → network-first (deploys land on the next load), cache as fallback.
  if (req.mode === 'navigate' || req.destination === 'document') {
    event.respondWith(navigationNetworkFirst(req, SHELL_CACHE, event));
    return;
  }

  // Versioned same-origin static assets → cache-first.
  if (url.origin === self.location.origin && url.search.includes('v=')) {
    event.respondWith(cacheFirst(req, STATIC_CACHE));
    return;
  }

  // Same-origin unversioned + Google Fonts + ESPN images → stale-while-revalidate.
  const isFont   = url.hostname === 'fonts.googleapis.com' || url.hostname === 'fonts.gstatic.com';
  const isImage  = url.hostname === 'a.espncdn.com';
  const isSame   = url.origin === self.location.origin;
  if (isSame || isFont || isImage) {
    event.respondWith(staleWhileRevalidate(req, RUNTIME_CACHE));
    return;
  }

  // Everything else: pass through.
});

// HTML navigations: try the network first so a deploy is live on the very next
// load, and fall back to the cached shell if the network is slow or gone.
// The cache lookup falls back to the precached /index.html or / when the exact
// URL — a deep link with a query, say — was never cached under its own key.
async function navigationNetworkFirst(req, cacheName, event) {
  const cache = await caches.open(cacheName);
  // Cache navigations under the bare pathname: deep links like ?player=slug all
  // serve the same shell, and per-query keys would strand a full index.html copy
  // for every distinct shared URL.
  const key = new URL(req.url).pathname;

  const network = fetch(req)
    .then((res) => {
      if (res && res.ok) cache.put(key, res.clone()).catch(() => {});
      return res;
    })
    .catch(() => null);

  // Race the fetch against the timeout. A failed fetch resolves null rather than
  // rejecting, so an offline visit drops to the cache immediately instead of
  // sitting out the full timeout.
  let timer;
  const timeout = new Promise((resolve) => { timer = setTimeout(() => resolve(null), NAV_TIMEOUT_MS); });
  const fresh = await Promise.race([network, timeout]);
  clearTimeout(timer);
  if (fresh && fresh.ok) return fresh;

  const cached = (await cache.match(key)) || (await cache.match('/index.html')) || (await cache.match('/'));
  if (cached) {
    // Serving stale because the network was slow, not because it failed — let the
    // fetch finish and refresh the cache. waitUntil keeps the worker alive for it,
    // otherwise the browser may kill us the moment we return the response.
    if (event && typeof event.waitUntil === 'function') event.waitUntil(network);
    return cached;
  }
  // Nothing cached: wait the fetch out rather than failing at the timeout.
  return (await network) || new Response('', { status: 504, statusText: 'offline' });
}

async function cacheFirst(req, cacheName) {
  const cached = await caches.match(req);
  if (cached) return cached;
  try {
    const res = await fetch(req);
    if (res && res.ok) {
      const copy = res.clone();
      caches.open(cacheName)
        .then((c) => c.put(req, copy).then(() => pruneSupersededVersions(c, req)))
        .catch(() => {});
    }
    return res;
  } catch (_) {
    return new Response('', { status: 504, statusText: 'offline' });
  }
}

// Daily ?v= bumps (ADP, betting lines) would otherwise strand each old entry in
// STATIC_CACHE forever — unbounded growth until quota eviction drops the whole
// cache. After caching a versioned asset, evict entries for the same pathname
// with a different query string.
async function pruneSupersededVersions(cache, req) {
  try {
    const path = new URL(req.url).pathname;
    const search = new URL(req.url).search;
    const keys = await cache.keys();
    await Promise.all(keys.map((k) => {
      const ku = new URL(k.url);
      return (ku.pathname === path && ku.search !== search) ? cache.delete(k) : null;
    }));
  } catch (_) { /* best-effort */ }
}

async function staleWhileRevalidate(req, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(req);
  const fetchAndUpdate = fetch(req)
    .then((res) => {
      if (res && res.ok) {
        // Same-origin only: camp_news / ud_adp_history carry an hour-granular ?d=
        // stamp, so without pruning every hour strands another ~300KB pair in
        // RUNTIME_CACHE. Cross-origin stays unpruned — ESPN combiner headshots all
        // share one pathname and differ only by query, so pruning would evict them.
        const sameOrigin = new URL(req.url).origin === self.location.origin;
        cache.put(req, res.clone())
          .then(() => sameOrigin ? pruneSupersededVersions(cache, req) : null)
          .catch(() => {});
      }
      return res;
    })
    .catch(() => cached);
  return cached || fetchAndUpdate;
}
