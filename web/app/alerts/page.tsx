import type { Metadata } from "next";
import { loadInbox } from "@/lib/data";
import AlertsView from "@/components/alerts/AlertsView";

export const metadata: Metadata = { title: "Alerts · FINN" };
export const dynamic = "force-static";

export default function Page() {
  return <AlertsView data={loadInbox()} />;
}
