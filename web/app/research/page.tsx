import type { Metadata } from "next";
import Link from "next/link";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { listCompanies } from "@/lib/research";
import s from "@/components/research/research.module.css";

export const metadata: Metadata = { title: "Research · Finn" };

export default function Page() {
  const companies = listCompanies().sort((a, b) => Number(!!b.doc) - Number(!!a.doc) || Number(!!b.focus) - Number(!!a.focus) || a.name.localeCompare(b.name));
  return (
    <div className={s.page}>
      <nav className={s.top}>
        <Link href="/" className={s.back}>
          <ChevronLeft size={18} strokeWidth={2} aria-hidden="true" /> Inbox
        </Link>
      </nav>
      <header className={s.head}>
        <p className={s.kicker}>Research</p>
        <h1 className={s.title}>Promises vs delivery</h1>
        <p className={s.sub}>What management guided on its calls, against what the reported numbers show.</p>
      </header>
      <ul className={s.index}>
        {companies.map((c) => (
          <li key={c.symbol}>
            <Link href={`/research/${c.symbol}`} className={s.indexRow}>
              <span className={s.indexText}>
                <span className={s.indexName}>
                  {c.name} <span className={`ticker ${s.ticker}`}>{c.symbol}</span>
                </span>
                <span className={s.indexMeta}>
                  {c.doc ? (c.doc.track_record?.text ?? statusLine(c.doc.status)) : "Not researched yet"}
                </span>
              </span>
              <ChevronRight size={18} strokeWidth={1.75} aria-hidden="true" className={s.chev} />
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

function statusLine(status: string): string {
  return (
    {
      no_transcripts: "Numbers only: no call transcripts on screener.in",
      no_promises: "Numbers only: no measurable guidance in the calls",
      numbers_only: "Numbers only",
      failed: "Last run failed",
    }[status] ?? status
  );
}
