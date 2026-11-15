"use client";

import { useEffect } from "react";

// The pre-paint script in layout.tsx sets the saved theme; a page React renders again on the
// client (the not-found page) resets <html data-theme>. Re-apply the saved choice after mount.
export default function ThemeKeeper() {
  useEffect(() => {
    try {
      if (localStorage.getItem("finn.theme") === "light") {
        document.documentElement.dataset.theme = "light";
        document.querySelector('meta[name="theme-color"]')?.setAttribute("content", "#f5f3ee");
      }
    } catch {
      /* storage blocked: stay on the default dark theme */
    }
  }, []);
  return null;
}
