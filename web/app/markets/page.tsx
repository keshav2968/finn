import type { Metadata } from "next";
import { loadQuotes } from "@/lib/data";
import MarketsView from "@/components/markets/MarketsView";

export const metadata: Metadata = { title: "Markets · FINN" };
export const dynamic = "force-static";

export default function Page() {
  return <MarketsView quotes={loadQuotes()} />;
}
