/* MyFantasyFootball service worker.
   Strategy:
   - HTML navigations  → network-first (users always see fresh deploys), cache fallback for offline.
   - Versioned static assets (/styles/*.css?v=…, /data/*.js?v=…) → cache-first (URL changes when content does).
   - Unversioned same-origin GETs and Google Fonts woff2 / ESPN images → stale-while-revalidate.
   - Firebase / ESPN / Sleeper / Cloudflare APIs → bypass entirely.
   Bump SW_VERSION when changing SW logic so old caches get wiped on activate. */

const SW_VERSION   = '2026-05-13';
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

  // HTML navigations → network-first.
  if (req.mode === 'navigate' || req.destination === 'document') {
    event.respondWith(networkFirst(req, SHELL_CACHE));
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

async function networkFirst(req, cacheName) {
  try {
    const res = await fetch(req);
    if (res && res.ok) {
      const copy = res.clone();
      caches.open(cacheName).then((c) => c.put(req, copy)).catch(() => {});
    }
    return res;
  } catch (_) {
    const cached = await caches.match(req);
    return cached || caches.match('/index.html') || new Response('', { status: 504, statusText: 'offline' });
  }
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
