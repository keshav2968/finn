"use client";

import { useCallback, useEffect, useState } from "react";

// Install state for this device. Chrome's beforeinstallprompt is captured by an inline
// script in layout.tsx (it can fire before React hydrates) and kept on window.__finnBip.

type BIP = Event & { prompt: () => Promise<void>; userChoice: Promise<{ outcome: "accepted" | "dismissed" }> };
declare global {
  interface Window {
    __finnBip?: BIP | null;
  }
}

export const INSTALL_KEY = "finn.install.v1"; // "dismissed" | "installed" | "ios-seen"
export type InstallState = "dismissed" | "installed" | "ios-seen" | null;

export function isStandalone(): boolean {
  if (typeof window === "undefined") return false;
  return (
    window.matchMedia("(display-mode: standalone)").matches ||
    window.matchMedia("(display-mode: fullscreen)").matches ||
    (navigator as Navigator & { standalone?: boolean }).standalone === true
  );
}

export function isIOS(): boolean {
  if (typeof navigator === "undefined") return false;
  return /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
}

export function readInstallState(): InstallState {
  try {
    return (localStorage.getItem(INSTALL_KEY) as InstallState) ?? null;
  } catch {
    return null;
  }
}

export function writeInstallState(v: Exclude<InstallState, null>) {
  try {
    localStorage.setItem(INSTALL_KEY, v);
  } catch {
    /* storage blocked: the banner may show again next visit */
  }
  window.dispatchEvent(new Event("finn:bip"));
}

export function useInstall() {
  const [ready, setReady] = useState(false);
  const [standalone, setStandalone] = useState(false);
  const [ios, setIos] = useState(false);
  const [canPrompt, setCanPrompt] = useState(false);
  const [state, setState] = useState<InstallState>(null);

  useEffect(() => {
    const sync = () => {
      setStandalone(isStandalone());
      setIos(isIOS());
      setCanPrompt(!!window.__finnBip);
      setState(readInstallState());
      setReady(true);
    };
    sync();
    const mq = window.matchMedia("(display-mode: standalone)");
    window.addEventListener("finn:bip", sync);
    mq.addEventListener?.("change", sync);
    return () => {
      window.removeEventListener("finn:bip", sync);
      mq.removeEventListener?.("change", sync);
    };
  }, []);

  const prompt = useCallback(async () => {
    const e = window.__finnBip;
    if (!e) return "unavailable" as const;
    window.__finnBip = null; // a prompt can be used once
    await e.prompt();
    const { outcome } = await e.userChoice;
    writeInstallState(outcome === "accepted" ? "installed" : "dismissed");
    return outcome;
  }, []);

  return { ready, standalone, ios, canPrompt, state, prompt };
}
