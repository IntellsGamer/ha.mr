/* Immutable-asset cache for the browser V26 Python/WebAssembly codec. */
const ASSET_PREFIXES = ["/static/pyodide/", "/static/codec/"];

self.addEventListener("install", (event) => {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (!ASSET_PREFIXES.some((prefix) => url.pathname.startsWith(prefix))) return;
  event.respondWith((async () => {
    const cache = await caches.open("ha-mr-browser-codec-assets");
    const cached = await cache.match(request);
    if (cached) return cached;
    const response = await fetch(request);
    if (response.ok) await cache.put(request, response.clone());
    return response;
  })());
});
