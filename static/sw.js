/* v0.8.59: service worker for the installable app.
   Rules:
   - /api/ is NEVER touched or stored: fees, grades, messages and files always come fresh from the server and are never left on a phone.
   - The page and its scripts are fetched from the network first, so a new version reaches everyone on the next open. The saved copy is used
     only when there is no connection, so the app still opens and says it is offline instead of showing the browser's error page.
   - Other sites (Google Fonts, class links) are left to the browser.
   Change VERSION when this file changes; old saved copies are then deleted. */
const VERSION = "v0.8.64";
const CACHE = "portal-shell-" + VERSION;
const SHELL = ["/", "/ui.js", "/learning.js", "/fees.js", "/admin.js", "/notify.js", "/staffroom.js", "/posts.js", "/i18n/en.json",
               "/icons/icon-192.png", "/icons/icon-512.png", "/icons/apple-touch-icon.png"];

const OFFLINE = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#0b4f5c"><title>Offline</title><style>body{margin:0;min-height:100vh;display:grid;place-items:center;
font-family:system-ui,-apple-system,"Segoe UI",sans-serif;background:#f0f6f6;color:#10262b;text-align:center;padding:24px;box-sizing:border-box}
img{width:72px;height:72px;border-radius:16px}h1{font-size:1.3rem;margin:16px 0 8px}p{color:#4a6468;margin:0 0 20px}
button{font:inherit;font-weight:700;background:#0b4f5c;color:#fff;border:0;border-radius:10px;padding:12px 22px;min-height:44px}</style></head>
<body><main><img src="/icons/icon-192.png" alt=""><h1>You're offline</h1><p>Connect to the internet to use the portal.</p>
<button onclick="location.reload()">Try again</button></main></body></html>`;

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => Promise.all(SHELL.map(u => c.add(new Request(u, {cache: "reload"})).catch(() => {}))))
    .then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k.startsWith("portal-shell-") && k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", e => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/") || url.pathname === "/sw.js") return;   // private data and the worker itself: never stored
  if (req.mode === "navigate") {
    e.respondWith(fetch(req).then(r => {
      if (r.ok && (url.pathname === "/" || url.pathname === "/index.html")) { const copy = r.clone(); caches.open(CACHE).then(c => c.put("/", copy)); }
      return r;
    }).catch(async () => (await caches.match(url.pathname === "/apply.html" ? req : "/")) ||
      new Response(OFFLINE, {headers: {"Content-Type": "text/html; charset=utf-8"}})));
    return;
  }
  e.respondWith(fetch(req).then(r => {
    if (r.ok && r.type === "basic") { const copy = r.clone(); caches.open(CACHE).then(c => c.put(req, copy)); }
    return r;
  }).catch(async () => (await caches.match(req, {ignoreSearch: true})) || Response.error()));
});
