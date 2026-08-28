// ManiFuels Service Worker — v6
// Scope: served from the repo root on GitHub Pages, so './' resolves to
// /manifuels/. Registered from index.html as a real file (a blob: URL is
// rejected by Chrome, which is why offline never worked before v4).

const CACHE = 'manifuels-v6';

const PRECACHE = [
  './',
  './index.html',
  './manifest.json',
  './favicon.ico',
  './icon-180.png',
  './icon-192.png',
  './icon-512.png',
  'https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Syne:wght@400;700;800&display=swap',
  'https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js'
];

// ── Install: precache core assets, one at a time so a single CDN failure
//    does not abort the whole install ──
self.addEventListener('install', e => {
  self.skipWaiting();
  e.waitUntil(
    caches.open(CACHE).then(c =>
      Promise.all(PRECACHE.map(u => c.add(u).catch(() => {})))
    )
  );
});

// ── Activate: drop old caches, take over open tabs ──
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// Let the page ask for an immediate update (used by the "update available" prompt)
self.addEventListener('message', e => {
  if (e.data === 'SKIP_WAITING') self.skipWaiting();
});

self.addEventListener('fetch', e => {
  const url = e.request.url;

  // Only GET is cacheable; never touch the app's writes.
  if (e.request.method !== 'GET') return;

  // Supabase must always go to the network. If it is cached, a stale row could
  // be served as fresh and the merge logic would treat it as the server's truth.
  if (url.includes('supabase.co') || url.includes('supabase.in') || url.includes('supabase.io')) return;

  // Fonts and Chart.js: cache-first, they never change at a fixed URL.
  if (url.includes('fonts.gstatic.com') || url.includes('fonts.googleapis.com') || url.includes('cdnjs.cloudflare.com')) {
    e.respondWith(
      caches.match(e.request).then(cached => cached || fetch(e.request).then(resp => {
        if (resp && resp.status === 200) {
          const clone = resp.clone();
          caches.open(CACHE).then(c => c.put(e.request, clone));
        }
        return resp;
      }).catch(() => new Response('', { status: 503 })))
    );
    return;
  }

  // The app shell: network-first so a deploy is picked up immediately,
  // cache as the offline fallback.
  if (e.request.mode === 'navigate' || url.endsWith('index.html') || url.endsWith('/')) {
    e.respondWith(
      fetch(e.request).then(resp => {
        if (resp && resp.status === 200) {
          const clone = resp.clone();
          caches.open(CACHE).then(c => c.put('./index.html', clone));
        }
        return resp;
      }).catch(() => caches.match('./index.html').then(cached => cached ||
        new Response('<h2 style="font-family:monospace;color:#00d4a0;background:#121212;padding:40px;margin:0;min-height:100vh">ManiFuels — offline, and no copy is cached yet. Open the app once with a connection.</h2>',
          { headers: { 'Content-Type': 'text/html' } })))
    );
    return;
  }

  // Everything else: cache, then network.
  e.respondWith(
    caches.match(e.request).then(cached => cached ||
      fetch(e.request).catch(() => new Response('', { status: 503 })))
  );
});
