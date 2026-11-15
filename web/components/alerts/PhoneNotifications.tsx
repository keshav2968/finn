"use client";

import { useCallback, useEffect, useState } from "react";
import { Check, Copy } from "lucide-react";
import { isIOS, isStandalone } from "../shell/install";
import u from "../ui.module.css";
import s from "./alerts.module.css";

// What actually works on this phone, checked live, and the one step that's missing.
// Web Push needs a server to send; FINN's sender is a manual GitHub Action that holds the
// private key as a secret. Only the public key is in the app (it's public by design).
const VAPID = process.env.NEXT_PUBLIC_VAPID_PUBLIC_KEY ?? "";

type State = {
  supported: boolean;
  pushSupported: boolean;
  permission: NotificationPermission | "unsupported";
  standalone: boolean;
  ios: boolean;
  worker: boolean;
  secure: boolean;
  subscribed: string | null;
};

function b64ToBytes(b64: string): Uint8Array {
  const pad = "=".repeat((4 - (b64.length % 4)) % 4);
  const raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

export default function PhoneNotifications() {
  const [st, setSt] = useState<State | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const refresh = useCallback(async () => {
    const supported = "Notification" in window && "serviceWorker" in navigator;
    const reg = "serviceWorker" in navigator ? await navigator.serviceWorker.getRegistration() : undefined;
    const sub = reg && "pushManager" in reg ? await reg.pushManager.getSubscription().catch(() => null) : null;
    setSt({
      supported,
      pushSupported: "PushManager" in window,
      permission: supported ? Notification.permission : "unsupported",
      standalone: isStandalone(),
      ios: isIOS(),
      worker: !!reg?.active,
      secure: window.isSecureContext,
      subscribed: sub ? JSON.stringify(sub.toJSON()) : null,
    });
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  if (!st) return <span className="skel" style={{ height: 120 }} aria-hidden="true" />;

  const iosNeedsInstall = st.ios && !st.standalone;
  const allow = async () => {
    setNote(null);
    const p = await Notification.requestPermission();
    if (p === "denied") setNote("Blocked. To change it, allow notifications for FINN in your phone's settings.");
    await refresh();
  };
  const test = async () => {
    setNote(null);
    const reg = await navigator.serviceWorker.ready;
    await reg.showNotification("FINN test notification", {
      body: "Notifications reach this phone. Alerts arrive like this when the sender runs.",
      icon: "/icon-192.png",
      tag: "finn-test",
    });
    setNote("Sent. If nothing appeared, check that Focus or Do Not Disturb is off.");
  };
  const subscribe = async () => {
    setNote(null);
    try {
      const reg = await navigator.serviceWorker.ready;
      await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(VAPID) as BufferSource });
      await refresh();
    } catch (e) {
      setNote(`This browser refused the subscription: ${(e as Error).message}`);
    }
  };
  const copy = async () => {
    if (!st.subscribed) return;
    await navigator.clipboard.writeText(st.subscribed).catch(() => undefined);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const rows: [string, string, boolean][] = [
    ["Notifications", !st.supported ? "Not supported in this browser" : st.permission === "granted" ? "Allowed" : st.permission === "denied" ? "Blocked" : "Not asked yet", st.permission === "granted"],
    ["Installed to Home Screen", st.standalone ? "Yes" : st.ios ? "No: iPhone needs this for notifications" : "No (not required here)", st.standalone || !st.ios],
    ["Service worker", st.worker ? "Running" : "Not running", st.worker],
    ["Secure connection", st.secure ? (location.protocol === "https:" ? "HTTPS" : "Yes (local)") : "No: notifications need HTTPS", st.secure],
    ["Sender", VAPID ? (st.subscribed ? "Subscribed: the GitHub Action can reach this phone" : "Set up: subscribe this phone below") : "Not set up for this deployment", !!VAPID && !!st.subscribed],
  ];

  return (
    <div className={s.notify}>
      <p className={s.plain}>
        {VAPID
          ? "Alerts are sent to subscribed phones by a GitHub Action you run; FINN itself has no server."
          : "FINN has no server, so nothing is sent to your phone while the app is closed. You can check that notifications work on this phone with a test."}
      </p>
      <dl className={s.status}>
        {rows.map(([k, v, ok]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd data-ok={ok || undefined}>{v}</dd>
          </div>
        ))}
      </dl>
      <div className={s.actions}>
        {st.supported && st.permission === "default" && !iosNeedsInstall && (
          <button type="button" className={`${s.go} press`} onClick={() => void allow()}>
            Allow notifications
          </button>
        )}
        {st.supported && st.permission === "granted" && (
          <button type="button" className={`${u.chip} press`} onClick={() => void test()}>
            Send a test notification
          </button>
        )}
        {VAPID && st.pushSupported && st.permission === "granted" && !st.subscribed && (
          <button type="button" className={`${s.go} press`} onClick={() => void subscribe()}>
            Subscribe this phone
          </button>
        )}
        {st.subscribed && (
          <button type="button" className={`${u.chip} press`} onClick={() => void copy()}>
            {copied ? <Check size={15} strokeWidth={2.5} aria-hidden="true" /> : <Copy size={15} strokeWidth={2} aria-hidden="true" />}
            {copied ? "Copied" : "Copy subscription for the sender"}
          </button>
        )}
      </div>
      {iosNeedsInstall && <p className={s.plain}>On iPhone, add FINN to your Home Screen first (Install FINN, above), then open it from there and allow notifications.</p>}
      {note && (
        <p className={s.plain} role="status">
          {note}
        </p>
      )}
    </div>
  );
}
