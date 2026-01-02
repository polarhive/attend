// Service Worker for caching attendance tracker assets
const CACHE_NAME = 'attendance-tracker-' + 'commit-hash';
const urlsToCache = [
  '/index.html',
  '/style.min.css',
  '/bundle.min.js',
  '/favicon.ico',
];

// Install event - cache the assets
self.addEventListener('install', function (event) {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(function (cache) {
        return cache.addAll(urlsToCache);
      })
      .then(function () {
        // Force the waiting service worker to become the active service worker
        return self.skipWaiting();
      })
  );
});

// Activate event - clean up old caches
self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches.keys().then(function (cacheNames) {
      return Promise.all(
        cacheNames.map(function (cacheName) {
          if (cacheName !== CACHE_NAME) {
            return caches.delete(cacheName);
          }
        })
      );
    }).then(function () {
      // Ensure the service worker takes control of all clients immediately
      return self.clients.claim();
    })
  );
});

// Fetch event - serve from cache when possible
self.addEventListener('fetch', function (event) {
  const requestUrl = new URL(event.request.url);

  // Handle API requests differently - always try network first for fresh data
  if (requestUrl.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(event.request)
        .then(function (response) {
          return response;
        })
        .catch(function (error) {
          // Could return a cached error page or default response here
          throw error;
        })
    );
    return;
  }

  // For all other requests, try cache first, then network
  event.respondWith(
    caches.match(event.request)
      .then(function (response) {
        // Return cached version if available
        if (response) {
          return response;
        }

        // Otherwise fetch from network
        return fetch(event.request).then(function (response) {
          // Don't cache if not a valid response
          if (!response || response.status !== 200 || response.type !== 'basic') {
            return response;
          }

          // Clone the response for caching
          const responseToCache = response.clone();

          caches.open(CACHE_NAME)
            .then(function (cache) {
              cache.put(event.request, responseToCache);
            });

          return response;
        });
      })
  );
});

// Handle service worker updates
self.addEventListener('message', function (event) {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});
