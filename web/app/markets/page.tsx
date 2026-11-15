import type { Metadata } from "next";
import { loadQuotes, loadSectorHues, logoSymbols } from "@/lib/data";
import MarketsView from "@/components/markets/MarketsView";

export const metadata: Metadata = { title: "Markets · FINN" };
export const dynamic = "force-static";

export default function Page() {
  return <MarketsView quotes={loadQuotes()} logos={logoSymbols()} hues={loadSectorHues()} />;
}
