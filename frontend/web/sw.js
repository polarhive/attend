const CACHE_NAME = 'attend-pwa-v1';
const ASSETS = [
  'index.html',
  'style.css',
  'script.js',
  'i.js',
  'chart.min.js',
  'mapping.json',
  'manifest.json',
  'favicon.ico'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(
      keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
    ))
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  const req = event.request;

  // Navigation requests -> try network first, fall back to cached `index.html` (main app shows cached attendance)
  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req)
        .then(res => {
          const copy = res.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(req, copy));
          return res;
        })
        .catch(() => caches.match('index.html'))
    );
    return;
  }

  // Other requests -> cache-first, then network; cache what we fetch
  event.respondWith(
    caches.match(req).then(cached => {
      if (cached) return cached;
      return fetch(req)
        .then(networkRes => {
          // only cache GET same-origin responses
          if (req.method === 'GET' && new URL(req.url).origin === location.origin) {
            caches.open(CACHE_NAME).then(cache => cache.put(req, networkRes.clone()));
          }
          return networkRes;
        })
        .catch(() => {
          // fallback for images/icons
          if (req.destination === 'image') return caches.match('icons/icon.svg');
        });
    })
  );
});