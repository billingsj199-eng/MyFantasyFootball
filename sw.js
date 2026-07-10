/* MyFantasyFootball service worker.
   Strategy:
   - HTML navigations  → stale-while-revalidate: serve the cached shell instantly (~0ms),
     refetch in the background so the NEXT load gets the newest deploy. Trades one-visit-behind
     freshness for a ~330–440ms faster repeat load (the network HTML fetch is off the critical
     path). First-ever visit (no cache) still awaits the network.
   - Versioned static assets (/styles/*.css?v=…, /data/*.js?v=…) → cache-first (URL changes when content does).
   - Unversioned same-origin GETs and Google Fonts woff2 / ESPN images → stale-while-revalidate.
   - Firebase / ESPN / Sleeper / Cloudflare APIs → bypass entirely.
   Bump SW_VERSION when changing SW logic so old caches get wiped on activate. */

const SW_VERSION   = '2026-07-10c';
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

  // HTML navigations → stale-while-revalidate (instant repeat loads, background refresh).
  if (req.mode === 'navigate' || req.destination === 'document') {
    event.respondWith(navigationSWR(req, SHELL_CACHE));
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

// HTML navigations: serve the cached shell instantly (falling back to the precached
// /index.html or / when the exact URL — e.g. a deep link with a query — isn't cached),
// and revalidate in the background so the next load gets the freshest deploy. Only awaits
// the network when there's nothing cached at all (first-ever visit / cleared cache).
async function navigationSWR(req, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = (await cache.match(req)) || (await cache.match('/index.html')) || (await cache.match('/'));
  const network = fetch(req)
    .then((res) => {
      if (res && res.ok) cache.put(req, res.clone()).catch(() => {});
      return res;
    })
    .catch(() => null);
  return cached || (await network) || new Response('', { status: 504, statusText: 'offline' });
}

async function cacheFirst(req, cacheName) {
  const cached = await caches.match(req);
  if (cached) return cached;
  try {
    const res = await fetch(req);
    if (res && res.ok) {
      const copy = res.clone();
      caches.open(cacheName).then((c) => c.put(req, copy)).catch(() => {});
    }
    return res;
  } catch (_) {
    return new Response('', { status: 504, statusText: 'offline' });
  }
}

async function staleWhileRevalidate(req, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(req);
  const fetchAndUpdate = fetch(req)
    .then((res) => {
      if (res && res.ok) cache.put(req, res.clone()).catch(() => {});
      return res;
    })
    .catch(() => cached);
  return cached || fetchAndUpdate;
}
