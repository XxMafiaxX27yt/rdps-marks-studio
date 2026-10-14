// Offline support: after the first visit the site opens instantly and works without internet.
// Big library files are kept (cache-first); the app's own files are refreshed when online (network-first).
const VENDOR = "rdps-vendor-v1";
const APP = "rdps-app-v1";

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;           // model downloads are cached by the AI library itself
  const big = url.pathname.includes("/vendor/") || url.pathname.includes("/py/wheels/");
  if (big) {
    e.respondWith(caches.open(VENDOR).then(async (c) => {
      const hit = await c.match(req);
      if (hit) return hit;
      const res = await fetch(req);
      if (res.ok) c.put(req, res.clone());
      return res;
    }));
    return;
  }
  e.respondWith(caches.open(APP).then(async (c) => {
    try {
      const res = await fetch(req);
      if (res.ok) c.put(req, res.clone());
      return res;
    } catch (err) {
      const hit = await c.match(req, { ignoreSearch: true });
      if (hit) return hit;
      throw err;
    }
  }));
});
