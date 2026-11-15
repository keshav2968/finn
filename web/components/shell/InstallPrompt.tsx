"use client";

import { useEffect, useState } from "react";
import { SquarePlus, Share, X } from "lucide-react";
import Sheet from "../Sheet";
import sh from "../sheet.module.css";
import { useInstall, writeInstallState } from "./install";
import s from "./shell.module.css";

// Android: our own banner from beforeinstallprompt, after the first interaction.
// iOS: no install API, so a one-time sheet with the Share → Add to Home Screen steps.
// Neither shows once FINN runs standalone, or after it was dismissed or installed.
export default function InstallPrompt() {
  const { ready, standalone, ios, canPrompt, state, prompt } = useInstall();
  const [interacted, setInteracted] = useState(false);
  const [iosOpen, setIosOpen] = useState(false);

  useEffect(() => {
    // The first tap or key press anywhere that isn't inside an open sheet.
    const on = (e: Event) => {
      if ((e.target as Element | null)?.closest?.('[role="dialog"]')) return;
      setInteracted(true);
    };
    window.addEventListener("pointerup", on, { passive: true });
    window.addEventListener("keydown", on);
    return () => {
      window.removeEventListener("pointerup", on);
      window.removeEventListener("keydown", on);
    };
  }, []);

  const iosEligible = ready && ios && !standalone && state === null;
  useEffect(() => {
    if (!iosEligible || !interacted) return;
    // Wait a beat so the sheet never lands on top of what the tap just opened.
    const t = setTimeout(() => {
      if (!document.querySelector('[role="dialog"]')) setIosOpen(true);
      else setInteracted(false); // try again after the next interaction
    }, 1200);
    return () => clearTimeout(t);
  }, [iosEligible, interacted]);

  if (!ready || standalone) return null;

  if (iosOpen) {
    return (
      <Sheet
        open
        label="Install FINN"
        onClose={() => {
          writeInstallState("ios-seen");
          setIosOpen(false);
        }}
      >
        <IosSteps />
      </Sheet>
    );
  }

  const showBanner = !ios && canPrompt && interacted && state === null;
  if (!showBanner) return null;
  return (
    <div className={s.banner} role="region" aria-label="Install FINN">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src="/icon-192.png" alt="" className={s.bannerIcon} width={40} height={40} />
      <span className={s.bannerText}>
        <strong>Install FINN</strong>
        Full screen, one tap from your home screen.
      </span>
      <button type="button" className={`${s.bannerGo} press`} onClick={() => void prompt()}>
        Install
      </button>
      <button type="button" className={s.bannerX} aria-label="Not now" onClick={() => writeInstallState("dismissed")}>
        <X size={18} strokeWidth={2} />
      </button>
    </div>
  );
}

export function IosSteps() {
  return (
    <>
      <h2 className={sh.title}>Install FINN</h2>
      <p className={sh.sub}>iPhone and iPad add web apps from the Share menu. It takes three taps.</p>
      <ol className={s.steps}>
        <li>
          <span>
            Tap <strong>Share</strong>
            <span className={s.glyph} aria-hidden="true">
              <Share size={15} strokeWidth={2} />
            </span>
            : at the bottom of the screen in Safari, or in the address bar in Chrome.
          </span>
        </li>
        <li>
          <span>
            Scroll down and tap <strong>Add to Home Screen</strong>
            <span className={s.glyph} aria-hidden="true">
              <SquarePlus size={15} strokeWidth={2} />
            </span>
            .
          </span>
        </li>
        <li>
          <span>
            Tap <strong>Add</strong>. FINN opens full screen from its icon, like any app.
          </span>
        </li>
      </ol>
    </>
  );
}
