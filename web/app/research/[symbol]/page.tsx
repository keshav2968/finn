import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { listCompanies, loadResearch } from "@/lib/research";
import ResearchView, { NotRun } from "@/components/research/ResearchView";

// One static page per known company (portfolio + any ticker with a research file),
// rebuilt on every data commit. An unknown ticker is a 404, not a live fetch.
export const dynamicParams = false;

export function generateStaticParams() {
  return listCompanies().map((c) => ({ symbol: c.symbol }));
}

type Props = { params: Promise<{ symbol: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { symbol } = await params;
  const company = listCompanies().find((c) => c.symbol === symbol);
  return { title: `${company?.name ?? symbol} · Finn research` };
}

export default async function Page({ params }: Props) {
  const { symbol } = await params;
  const company = listCompanies().find((c) => c.symbol === symbol);
  if (!company) notFound();
  const doc = loadResearch(symbol);
  return doc ? <ResearchView doc={doc} focus={company.focus} /> : <NotRun company={company} />;
}
