#!/usr/bin/env node
// Sends FINN's current alerts as one Web Push notification to the subscriptions you saved.
// Runs on GitHub Actions (.github/workflows/push.yml) or your own machine; never in the app.
//
// Environment (GitHub secrets; never committed, never in the browser bundle):
//   VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY   from `npx web-push generate-vapid-keys`
//   VAPID_SUBJECT                         mailto: address for push services to reach you
//   PUSH_SUBSCRIPTIONS                    JSON: one subscription object or an array of them
//                                         (copy it from Alerts → Phone notifications in the app)
// Usage: node scripts/send-push.mjs [--dry-run] [--alerts ../data/seed/push/alerts.json]

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const args = process.argv.slice(2);
const dry = args.includes("--dry-run");
const at = args.indexOf("--alerts");
const file = resolve(at >= 0 ? args[at + 1] : new URL("../../data/seed/push/alerts.json", import.meta.url).pathname);

export function buildMessage(doc) {
  const alerts = [...(doc.alerts ?? [])].sort((a, b) => (b.date ?? "").localeCompare(a.date ?? ""));
  if (!alerts.length) return null;
  const lines = alerts.slice(0, 3).map((a) => `${a.symbol}: ${a.reason}`);
  const more = alerts.length > 3 ? ` and ${alerts.length - 3} more` : "";
  return {
    title: `FINN: ${alerts.length} alert${alerts.length === 1 ? "" : "s"}`,
    body: `${lines.join(" · ")}${more}`,
    tag: `finn-${doc.snapshot_at ?? "alerts"}`,
    url: "/alerts",
  };
}

async function main() {
  const doc = JSON.parse(readFileSync(file, "utf8"));
  const msg = buildMessage(doc);
  if (!msg) {
    console.log("No alerts in", file, "- nothing to send.");
    return;
  }
  console.log("Message:", JSON.stringify(msg));
  if (dry) return;

  const { VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY, VAPID_SUBJECT, PUSH_SUBSCRIPTIONS } = process.env;
  const missing = ["VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "VAPID_SUBJECT", "PUSH_SUBSCRIPTIONS"].filter((k) => !process.env[k]);
  if (missing.length) {
    console.error(`Not sent: set ${missing.join(", ")} (see README, Phone notifications).`);
    process.exit(1);
  }
  const webpush = (await import("web-push")).default;
  webpush.setVapidDetails(VAPID_SUBJECT, VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY);
  const parsed = JSON.parse(PUSH_SUBSCRIPTIONS);
  const subs = Array.isArray(parsed) ? parsed : [parsed];
  let ok = 0;
  for (const sub of subs) {
    try {
      await webpush.sendNotification(sub, JSON.stringify(msg), { TTL: 6 * 3600 });
      ok += 1;
    } catch (e) {
      // 404/410: the phone dropped this subscription; turn notifications on again in the app.
      console.error(`Failed for ${new URL(sub.endpoint).host}: ${e.statusCode ?? ""} ${e.body ?? e.message}`);
    }
  }
  console.log(`Sent to ${ok} of ${subs.length} subscription(s).`);
  if (!ok) process.exit(1);
}

if (import.meta.url === `file://${process.argv[1]}`) main();
