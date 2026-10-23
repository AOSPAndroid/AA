/* Network-only navigation and persistent Atlas alerts. No cache or push provider. */
"use strict";
self.addEventListener("install", event => event.waitUntil(self.skipWaiting()));
self.addEventListener("activate", event => event.waitUntil(self.clients.claim()));
self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  if (event.request.mode !== "navigate" || url.origin !== self.location.origin ||
      !["/", "/installer", "/installer/"].includes(url.pathname)) return;
  event.respondWith(fetch(event.request).catch(() => new Response(`<!doctype html>
    <html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Start Atlas</title><style>body{font:15px/1.6 system-ui;background:#f8f9fb;color:#172b3a;max-width:480px;margin:12vh auto;padding:24px}a{color:#007fa3}</style>
    <h1>Atlas is not running</h1><p>Start Atlas using your usual Start-Office-Atlas.bat or Start-All-Atlas.bat launcher, then reopen the app.</p>
    <p>On your work PC, run the launcher from the elevated Atlas account and keep your normal Outlook/Teams account signed in.</p>
    <a href="/installer?command=inbox">Retry Atlas</a></html>`, {
      status: 503, headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" },
    })));
});
self.addEventListener("notificationclick", event => {
  event.notification.close();
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    const client = windows.find(item => item.frameType === "top-level" && new URL(item.url).origin === self.location.origin &&
      ["/", "/installer", "/installer/"].includes(new URL(item.url).pathname));
    if (client) { await client.focus(); client.postMessage({ type: "atlas-open-inbox" }); }
    else await self.clients.openWindow("/installer?command=inbox");
  })());
});
