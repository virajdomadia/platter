// Platter app-shell service worker (rider PWA). Deliberately tiny: it only lets the installed
// rider app open when the network blips. It never touches the API, the event streams, map tiles or
// anything cross-origin — those must always be live.
const CACHE = "platter-shell-v2";
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

  if (!url.pathname.startsWith("/rider")) return; // the offline shell is the rider app's only

  event.respondWith(
    fetch(req).catch(() =>
      caches.match("/rider").then((hit) => hit || new Response("Offline", { status: 503, headers: { "Content-Type": "text/plain" } })),
    ),
  );
});

// v2 Web Push: the API sends fixed templates { title, body, url, tag }; a click opens that page
// (same origin only), reusing an open tab when there is one.
self.addEventListener("push", (event) => {
  let d = {};
  try {
    d = event.data ? event.data.json() : {};
  } catch {
    d = {};
  }
  const title = typeof d.title === "string" ? d.title : "Platter";
  event.waitUntil(
    self.registration.showNotification(title, {
      body: typeof d.body === "string" ? d.body : "",
      tag: typeof d.tag === "string" ? d.tag : undefined,
      icon: "/apple-icon.png",
      badge: "/apple-icon.png",
      data: { url: typeof d.url === "string" ? d.url : "/" },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = new URL((event.notification.data && event.notification.data.url) || "/", self.location.origin);
  if (url.origin !== self.location.origin) return;
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((tabs) => {
      const open = tabs.find((t) => new URL(t.url).pathname === url.pathname);
      if (open) return open.focus();
      return self.clients.openWindow(url.href);
    }),
  );
});
