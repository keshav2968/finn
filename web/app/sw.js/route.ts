// /sw.js, generated once per build so each deploy gets its own cache name.
//
// What it caches: only same-origin GET responses for FINN's own pages, their data payloads
// and hashed static assets. All of it is public snapshot data: there are no accounts,
// tokens or personal data anywhere in the app. Cross-origin requests (BSE filing PDFs)
// and anything not a GET pass straight through and are never stored.

import { logoSymbols } from "@/lib/data";

export const dynamic = "force-static";

const BUILD = process.env.VERCEL_GIT_COMMIT_SHA?.slice(0, 12) ?? String(Date.now());
const LOGO_URLS = logoSymbols().map((s) => `/logos/${encodeURIComponent(s)}.png`);

const source = `
const CACHE = "finn-${BUILD}";
const SHELL = ["/", "/markets", "/research", "/alerts", "/manifest.webmanifest", "/icon-192.png", "/icon-512.png"];
// Company logos: the files saved in web/public/logos at build time, so they work offline.
const LOGOS = ${JSON.stringify(LOGO_URLS)};

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((c) => c.addAll(SHELL).then(() => Promise.all(LOGOS.map((u) => c.add(u).catch(() => null)))))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith("finn-") && k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

function cacheable(res) {
  return res && res.ok && res.type === "basic";
}

// Web Push: a message sent by scripts/send-push.mjs (run from a GitHub Action, where the
// VAPID private key lives as a secret). Nothing here holds a key.
self.addEventListener("push", (event) => {
  let msg = {};
  try { msg = event.data ? event.data.json() : {}; } catch (e) { msg = { body: event.data && event.data.text() }; }
  const title = msg.title || "FINN";
  event.waitUntil(self.registration.showNotification(title, {
    body: msg.body || "",
    icon: "/icon-192.png",
    badge: "/icon-192.png",
    tag: msg.tag || "finn-alerts",
    data: { url: msg.url || "/alerts" },
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/alerts";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
      for (const c of list) { if ("focus" in c) { c.navigate(url); return c.focus(); } }
      return self.clients.openWindow(url);
    }),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return; // filings on bseindia.com etc.: never touched
  if (url.pathname === "/sw.js") return;

  // Hashed build assets, icons and company logos only change with a deploy: cache first.
  if (url.pathname.startsWith("/_next/static/") || /^\\/icon[-.]/.test(url.pathname) || url.pathname.startsWith("/logos/")) {
    event.respondWith(
      caches.match(req).then((hit) => hit || fetch(req).then((res) => {
        if (cacheable(res)) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(req, copy)); }
        return res;
      })),
    );
    return;
  }

  // Pages and their data: network first, so a new deploy shows at once; the cached copy
  // keeps FINN usable offline.
  const isPage = req.mode === "navigate";
  const isData = req.headers.get("RSC") === "1" || url.searchParams.has("_rsc");
  if (isPage || isData) {
    event.respondWith(
      fetch(req)
        .then((res) => {
          if (cacheable(res)) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(req, copy)); }
          return res;
        })
        .catch(() => caches.match(req).then((hit) => hit || (isPage ? caches.match("/") : Response.error()))),
    );
  }
});
`;

export function GET() {
  return new Response(source, {
    headers: {
      "Content-Type": "application/javascript; charset=utf-8",
      "Cache-Control": "no-cache",
      "Service-Worker-Allowed": "/",
    },
  });
}
