"use client";

import { useEffect } from "react";
import { markHydrated } from "../motion";

// Registers /sw.js in production builds only (a dev server must never be cached).
export default function ServiceWorker() {
  useEffect(() => {
    markHydrated(); // last in the layout, so it runs after the first page's own effects
    if (process.env.NODE_ENV !== "production" || !("serviceWorker" in navigator)) return;
    const go = () => navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => undefined);
    if (document.readyState === "complete") go();
    else window.addEventListener("load", go, { once: true });
  }, []);
  return null;
}
