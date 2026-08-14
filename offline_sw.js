/* Offline-first shell and exact V26 runtime cache. */
const CACHE_VERSION = "ha-mr-offline-v9";
const APP_SHELL = [
  { url: "/", bytes: 36_000 },
  { url: "/static/app.css?v=v26-browser-15", bytes: 9_000 },
  { url: "/static/qrcode.js?v=local-qr-1", bytes: 23_467 },
  { url: "/static/app.js?v=v26-browser-15", bytes: 15_000 },
  { url: "/static/browser_codec_runtime.js?v=v26-browser-15", bytes: 8_000 },
  { url: "/static/codec/v26/manifest.json?v=v26-browser-15", bytes: 2_000 },
  { url: "/static/codec/v26/conformance.json", bytes: 2_660 },
  { url: "/static/codec/v26/ha_mr_v26.zip", bytes: 142_572 },
  { url: "/static/pyodide/0.26.3/pyodide.js", bytes: 14_767 },
  { url: "/static/pyodide/0.26.3/pyodide.asm.js", bytes: 1_228_169 },
  { url: "/static/pyodide/0.26.3/pyodide.asm.wasm", bytes: 10_086_131 },
  { url: "/static/pyodide/0.26.3/python_stdlib.zip", bytes: 2_341_797 },
  { url: "/static/pyodide/0.26.3/pyodide-lock.json", bytes: 106_335 },
];

function formatBytes(bytes) {
  return `${(bytes / 1024 / 1024).toFixed(bytes >= 1024 * 1024 ? 1 : 2)} MB`;
}

async function notifyClients(message) {
  const clients = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
  for (const client of clients) client.postMessage(message);
}

async function precacheApplication() {
  const cache = await caches.open(CACHE_VERSION);
  const totalBytes = APP_SHELL.reduce((total, asset) => total + asset.bytes, 0);
  let completedBytes = 0;

  await notifyClients({
    type: "ha-mr-precache-progress",
    stage: "download",
    message: `Downloading browser codec assets… ${formatBytes(0)} / ${formatBytes(totalBytes)}`,
    progress: 0,
  });

  for (const asset of APP_SHELL) {
    const response = await fetch(asset.url, { cache: "reload" });
    if (!response.ok) throw new Error(`Could not precache ${asset.url}.`);
    await cache.put(asset.url, response);
    completedBytes += asset.bytes;
    await notifyClients({
      type: "ha-mr-precache-progress",
      stage: "download",
      message: `Downloading browser codec assets… ${formatBytes(completedBytes)} / ${formatBytes(totalBytes)}`,
      progress: Math.round((completedBytes / totalBytes) * 100),
    });
  }
}

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    await precacheApplication();
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names
      .filter((name) => name.startsWith("ha-mr-offline-") && name !== CACHE_VERSION)
      .map((name) => caches.delete(name)));
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === "navigate") {
    event.respondWith((async () => {
      const cache = await caches.open(CACHE_VERSION);
      try {
        const network = await fetch(request);
        if (network.ok) await cache.put("/", network.clone());
        return network;
      } catch (_) {
        return (await cache.match("/")) || Response.error();
      }
    })());
    return;
  }

  if (!url.pathname.startsWith("/static/")) return;
  event.respondWith((async () => {
    const cache = await caches.open(CACHE_VERSION);
    const cached = await cache.match(request, { ignoreSearch: false });
    if (cached) return cached;
    try {
      const network = await fetch(request);
      if (network.ok) await cache.put(request, network.clone());
      return network;
    } catch (_) {
      return Response.error();
    }
  })());
});
