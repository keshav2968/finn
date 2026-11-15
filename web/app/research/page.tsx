import type { Metadata } from "next";
import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { listCompanies } from "@/lib/research";
import TickerSearch from "@/components/research/TickerSearch";
import u from "@/components/ui.module.css";
import s from "@/components/research/research.module.css";

export const metadata: Metadata = { title: "Research · FINN" };

const VERDICT_ORDER = ["Delivered", "Missed", "Goalposts moved", "Pending", "Unverified"] as const;

export default function Page() {
  const companies = listCompanies().sort((a, b) => a.name.localeCompare(b.name));
  const done = companies.filter((c) => c.doc);
  const notYet = companies.filter((c) => !c.doc);
  return (
    <div className={u.page}>
      <header className={u.head}>
        <div className={u.titleRow}>
          <h1 className={u.title}>Research</h1>
        </div>
        <p className={u.sub}>
          What management promised on earnings calls, checked against the numbers it reported later. Sources: call transcripts
          and screener.in.
        </p>
      </header>

      <TickerSearch known={companies.map((c) => ({ symbol: c.symbol, name: c.name }))} />

      <section className={u.section} aria-labelledby="done">
        <h2 id="done" className={u.sectionHead}>
          Researched <span>{done.length}</span>
        </h2>
        <ul className={s.cards}>
          {done.map((c, i) => {
            const counts = c.doc!.track_record?.counts;
            const total = counts ? Object.values(counts).reduce((n, v) => n + v, 0) : 0;
            return (
              <li key={c.symbol}>
                <Link href={`/research/${c.symbol}`} className={`${s.card} row`}>
                  <span className={s.cardHead}>
                    <span className={s.indexName}>{c.name}</span>
                    <span className={`ticker ${s.ticker}`}>{c.symbol}</span>
                    <ChevronRight size={18} strokeWidth={1.75} aria-hidden="true" className={s.chev} />
                  </span>
                  <span className={s.indexMeta}>{c.doc!.track_record?.text ?? statusLine(c.doc!.status)}</span>
                  {counts && total > 0 && (
                    <>
                      <span className={s.verdictBar} aria-hidden="true">
                        {VERDICT_ORDER.filter((v) => counts[v]).map((v) => (
                          <span key={v} data-v={v} style={{ flexGrow: counts[v] }} />
                        ))}
                      </span>
                      <span className={s.verdictKey}>
                        {VERDICT_ORDER.filter((v) => counts[v]).map((v) => (
                          <span key={v}>
                            <i data-v={v} aria-hidden="true" /> {counts[v]} {v.toLowerCase()}
                          </span>
                        ))}
                      </span>
                    </>
                  )}
                </Link>
              </li>
            );
          })}
        </ul>
      </section>

      {notYet.length > 0 && (
        <section className={u.section} aria-labelledby="todo">
          <h2 id="todo" className={u.sectionHead}>
            Not researched yet <span>{notYet.length}</span>
          </h2>
          <ul className={s.index}>
            {notYet.map((c) => (
              <li key={c.symbol}>
                <Link href={`/research/${c.symbol}`} className={`${s.indexRow} row`}>
                  <span className={s.indexText}>
                    <span className={s.indexName}>
                      {c.name} <span className={`ticker ${s.ticker}`}>{c.symbol}</span>
                    </span>
                    <span className={s.indexMeta}>Numbers and the command to run it</span>
                  </span>
                  <ChevronRight size={18} strokeWidth={1.75} aria-hidden="true" className={s.chev} />
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
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
