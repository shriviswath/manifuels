// ManiFuels Service Worker — v4
// Real file SW: correct scope, proper offline support for GitHub Pages

const CACHE = 'manifuels-v4';

const PRECACHE = [
  './',
  './index.html',
  'https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Syne:wght@400;700;800&display=swap',
  'https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js'
];

// ── Install: precache core assets ──
self.addEventListener('install', e => {
  self.skipWaiting();
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(PRECACHE).catch(() => {}))
  );
});

// ── Activate: clear old caches ──
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// ── Fetch: network-first for API, cache-first for assets ──
self.addEventListener('fetch', e => {
  const url = e.request.url;

  // Never intercept Supabase API calls — always go live
  if (url.includes('supabase.co') || url.includes('supabase.io')) return;

  // For font CDN and Chart.js — cache first, then network
  if (url.includes('fonts.gstatic.com') || url.includes('fonts.googleapis.com') || url.includes('cdnjs.cloudflare.com')) {
    e.respondWith(
      caches.match(e.request).then(cached => {
        if (cached) return cached;
        return fetch(e.request).then(resp => {
          if (resp && resp.status === 200) {
            const clone = resp.clone();
            caches.open(CACHE).then(c => c.put(e.request, clone));
          }
          return resp;
        }).catch(() => new Response('', { status: 503 }));
      })
    );
    return;
  }

  // For the main app HTML — network first, fall back to cache
  if (e.request.mode === 'navigate' || url.endsWith('index.html') || url.endsWith('/')) {
    e.respondWith(
      fetch(e.request).then(resp => {
        if (resp && resp.status === 200) {
          const clone = resp.clone();
          caches.open(CACHE).then(c => c.put(e.request, clone));
        }
        return resp;
      }).catch(() =>
        caches.match('./index.html').then(cached => cached ||
          new Response('<h2 style="font-family:monospace;color:#00d4a0;padding:40px">ManiFuels — You are offline. Data will sync when reconnected.</h2>', {
            headers: { 'Content-Type': 'text/html' }
          })
        )
      )
    );
    return;
  }

  // Default: try cache, then network
  e.respondWith(
    caches.match(e.request).then(cached => {
      if (cached) return cached;
      return fetch(e.request).catch(() => new Response('', { status: 503 }));
    })
  );
});
