// Platter app-shell service worker (rider PWA). Deliberately tiny: it only lets the installed
// rider app open when the network blips. It never touches the API, the event streams, map tiles or
// anything cross-origin — those must always be live.
const CACHE = "platter-shell-v1";
const SHELL = ["/rider", "/favicon.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((c) => c.addAll(SHELL))
      .catch(() => undefined)
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return; // map tiles, fonts: straight to the network
  if (url.pathname.startsWith("/api/")) return; // API + EventSource: never cached
  if ((req.headers.get("accept") || "").includes("text/event-stream")) return;
  if (req.mode !== "navigate") return; // assets are content-hashed; the browser cache handles them

  event.respondWith(
    fetch(req).catch(() =>
      caches.match("/rider").then((hit) => hit || new Response("Offline", { status: 503, headers: { "Content-Type": "text/plain" } })),
    ),
  );
});
