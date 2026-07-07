const CACHE_NAME = 'aaron-billing-v3';
const ASSETS = [
  '/static/css/style.css',
  '/static/images/aronlogonow.png',
  '/static/images/icon-192.png',
  '/static/images/icon-512.png',
  '/static/manifest.json'
];

// Install Event - cache initial assets
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(ASSETS).catch(err => {
        console.warn('Pre-caching assets failed:', err);
      });
    })
  );
  self.skipWaiting();
});

// Activate Event - clean up old caches
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => {
      return Promise.all(
        keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key))
      );
    })
  );
  self.clients.claim();
});

// Fetch Event - network first with cache fallback
self.addEventListener('fetch', event => {
  // Only handle GET requests
  if (event.request.method !== 'GET') return;

  const url = new URL(event.request.url);
  const isStatic = url.pathname.startsWith('/static/');
  const isPrecached = ASSETS.includes(url.pathname);

  // Only intercept static assets or pre-cached files
  if (!isStatic && !isPrecached) {
    return; // Let browser handle dynamic/HTML pages normally without SW intervention
  }

  event.respondWith(
    fetch(event.request)
      .then(response => {
        // If response is valid and is a static asset, clone and cache it
        if (response && response.status === 200 && event.request.url.includes('/static/')) {
          const responseClone = response.clone();
          caches.open(CACHE_NAME).then(cache => {
            cache.put(event.request, responseClone);
          });
        }
        return response;
      })
      .catch(async () => {
        // Fallback to cache if network fails
        const cachedResponse = await caches.match(event.request);
        if (cachedResponse) {
          return cachedResponse;
        }
        // Return a valid offline text/plain response instead of undefined to prevent browser console TypeErrors
        return new Response("Resource unavailable offline", {
          status: 503,
          statusText: "Service Unavailable",
          headers: new Headers({ "Content-Type": "text/plain" })
        });
      })
  );
});
