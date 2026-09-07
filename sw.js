// ManiFuels Service Worker — v8
// Scope: served from the repo root on GitHub Pages, so './' resolves to
// /manifuels/. Registered from index.html as a real file (a blob: URL is
// rejected by Chrome, which is why offline never worked before v4).
//
// v8: supabase-js is served from ./vendor and precached. It used to come from
// cdn.jsdelivr.net, which was never in this list — so a cold start without a
// network left `window.supabase` undefined, `_supa` null, and every write
// parked in the outbox labelled "offline" while the app reported it was online
// and the sync dot stayed green.
const CACHE = 'manifuels-v8';
const PRECACHE = [
  './',
  './index.html',
  './manifest.json',
  './favicon.ico',
  './icon-180.png',
  './icon-192.png',
  './icon-512.png',
  // The only write path the app has. If this is missing on a cold offline
  // start, nothing can reach Supabase for the whole session.
  './vendor/supabase.min.js',
  'https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Syne:wght@400;700;800&display=swap',
  'https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js'
];

// Assets we cannot afford to lose. Everything in PRECACHE is attempted with
// its own catch so one CDN failure does not abort the install — but a silent
// miss on the Supabase bundle is exactly the failure this version exists to
// prevent, so it is logged loudly rather than swallowed.
const CRITICAL = ['./index.html', './vendor/supabase.min.js'];

// ── Install: precache core assets, one at a time so a single CDN failure
//    does not abort the whole install ──
self.addEventListener('install', e => {
  self.skipWaiting();
  e.waitUntil(
    caches.open(CACHE).then(c =>
      Promise.all(PRECACHE.map(u =>
        c.add(u).catch(err => {
          if (CRITICAL.indexOf(u) >= 0) {
            console.error('[sw] CRITICAL precache failed:', u, err && err.message);
          }
        })
      ))
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

// Is this a request to the Supabase API itself?
//
// The old test was `url.includes('supabase.co')`, matched against the whole URL
// string. That also matches a PATH containing those characters — so a vendored
// file at ./vendor/supabase.co.js, or any repo path with 'supabase.co' in it,
// would be treated as a live API call and never cached. `supabase.min.js`
// escaped the 'supabase.in' test by one character. Anchor it to the hostname.
function isSupabaseApi(u) {
  try {
    const h = new URL(u).hostname;
    return h.endsWith('.supabase.co') || h.endsWith('.supabase.in') ||
           h.endsWith('.supabase.io') || h === 'supabase.co';
  } catch (err) {
    return false;
  }
}

self.addEventListener('fetch', e => {
  const url = e.request.url;

  // Only GET is cacheable; never touch the app's writes.
  if (e.request.method !== 'GET') return;

  // Supabase must always go to the network. If it is cached, a stale row could
  // be served as fresh and the merge logic would treat it as the server's truth.
  if (isSupabaseApi(url)) return;

  // The vendored client, fonts and Chart.js: cache-first. These never change at
  // a fixed URL, and the cache name is bumped on every deploy that replaces one.
  if (url.indexOf('/vendor/') >= 0 ||
      url.indexOf('fonts.gstatic.com') >= 0 ||
      url.indexOf('fonts.googleapis.com') >= 0 ||
      url.indexOf('cdnjs.cloudflare.com') >= 0) {
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
