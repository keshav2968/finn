// Unread-alert count shared between tabs on this device (no server, no account).
export const UNREAD_ALERTS_KEY = "finn.alerts.unread";
export const UNREAD_ALERTS_EVENT = "finn:alerts";

export function publishUnreadAlerts(n: number) {
  try {
    localStorage.setItem(UNREAD_ALERTS_KEY, String(n));
  } catch {
    /* storage blocked */
  }
  window.dispatchEvent(new CustomEvent(UNREAD_ALERTS_EVENT, { detail: n }));
}
