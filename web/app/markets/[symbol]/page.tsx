import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { loadInbox, loadStock, portfolioSymbols } from "@/lib/data";
import { loadResearch } from "@/lib/research";
import StockView from "@/components/markets/StockView";

// One static page per holding. Prices are the snapshot's end-of-day series.
export const dynamicParams = false;

export function generateStaticParams() {
  return portfolioSymbols().map((symbol) => ({ symbol }));
}

type Props = { params: Promise<{ symbol: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { symbol } = await params;
  return { title: `${loadStock(symbol)?.quote.name ?? symbol} · FINN` };
}

export default async function Page({ params }: Props) {
  const { symbol } = await params;
  const stock = loadStock(symbol);
  if (!stock) notFound();
  const doc = loadResearch(symbol);
  return (
    <StockView
      quote={stock.quote}
      series={stock.series}
      data={loadInbox({ allItems: true, symbol })}
      research={doc ? { status: doc.status, text: doc.track_record?.text ?? null } : null}
    />
  );
}
