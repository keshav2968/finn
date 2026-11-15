import Link from "next/link";
import { Suspense } from "react";
import { ChevronLeft, ExternalLink } from "lucide-react";
import { amount, day, dayTime, pct } from "@/lib/format";
import type { CompanyEntry, LedgerEntry, ResearchDoc, Verdict } from "@/lib/research";
import Delta from "../Delta";
import AskedBanner from "./AskedBanner";
import Timeline from "./Timeline";
import s from "./research.module.css";

const VERDICT_TONE: Record<Verdict, string> = {
  Delivered: "pos",
  Missed: "neg",
  Pending: "neutral",
  "Goalposts moved": "moved",
  Unverified: "unverified",
};

function Sep() {
  return (
    <span className="sep" aria-hidden="true">
      ·
    </span>
  );
}

function Header({ symbol, name, sub }: { symbol: string; name: string; sub?: React.ReactNode }) {
  return (
    <>
      <nav className={s.top}>
        <Link href="/research" className={s.back}>
          <ChevronLeft size={18} strokeWidth={2} aria-hidden="true" /> Research
        </Link>
        <Link href={`/markets/${encodeURIComponent(symbol)}`} className={s.topLink}>
          Chart
        </Link>
      </nav>
      <header className={s.head}>
        <p className={s.kicker}>Promises vs delivery</p>
        <h1 className={s.title}>
          {name} <span className={`ticker ${s.ticker}`}>{symbol}</span>
        </h1>
        {sub && <p className={s.sub}>{sub}</p>}
      </header>
    </>
  );
}

export function NotRun({ company }: { company: CompanyEntry }) {
  return (
    <div className={s.page}>
      <Header symbol={company.symbol} name={company.name} />
      <Suspense fallback={null}>
        <AskedBanner />
      </Suspense>
      <section className={s.empty}>
        <h2>Not researched yet</h2>
        <p>
          {company.name}&apos;s promise ledger hasn&apos;t been built. It is made from primary sources only: the company&apos;s
          screener.in tables and its earnings-call transcripts.
        </p>
        {company.focus && <p className={s.focus}>What we&apos;d look at: {company.focus}</p>}
        <p className={s.cmd}>
          <code>python scripts/build_research.py {company.symbol}</code>
        </p>
      </section>
    </div>
  );
}

export default function ResearchView({ doc, focus }: { doc: ResearchDoc; focus: string | null }) {
  const calls = doc.transcripts.filter((t) => !t.error).length;
  return (
    <div className={s.page}>
      <Header
        symbol={doc.symbol}
        name={doc.name}
        sub={
          <>
            Built {dayTime(doc.generated_at)}
            <Sep />
            screener.in{calls ? ` + ${calls} call transcript${calls === 1 ? "" : "s"}` : ""}
          </>
        }
      />

      <Suspense fallback={null}>
        <AskedBanner />
      </Suspense>

      {doc.status === "failed" ? (
        <section className={s.empty}>
          <h2>This run failed</h2>
          <p>{doc.error}</p>
        </section>
      ) : (
        <>
          {focus && <p className={s.focus}>What we look at: {focus}</p>}

          {doc.numbers ? (
            <Numbers numbers={doc.numbers} />
          ) : (
            <p className={s.emptyLine}>screener.in tables could not be read on this run, so there are no numbers.</p>
          )}

          {doc.track_record && (
            <section className={s.record} aria-label="Track record">
              <p className={s.recordText}>{doc.track_record.text}</p>
              <div className={s.counts}>
                {(Object.keys(VERDICT_TONE) as Verdict[])
                  .filter((v) => doc.track_record!.counts[v])
                  .map((v) => (
                    <span key={v} className={s.verdict} data-tone={VERDICT_TONE[v]}>
                      {doc.track_record!.counts[v]} {v.toLowerCase()}
                    </span>
                  ))}
              </div>
              {doc.quiet?.map((q) => (
                <p key={q.metric} className={s.quiet}>
                  {q.text}
                </p>
              ))}
            </section>
          )}



          <section className={s.section}>
            <h2 className={s.sectionHead}>
              Promise ledger <span className={s.pill}>{doc.ledger.length}</span>
            </h2>
            {doc.ledger.length === 0 && <LedgerEmpty doc={doc} />}
            <div className={s.stack}>
              {orderLedger(doc.ledger).map((e) => (
                <Entry key={e.id} e={e} />
              ))}
            </div>
          </section>

          <Sources doc={doc} />
        </>
      )}
    </div>
  );
}

function orderLedger(entries: LedgerEntry[]): LedgerEntry[] {
  const rank = (e: LedgerEntry) => (e.metric === "other" ? 1 : 0);
  return [...entries].sort((a, b) => rank(a) - rank(b) || b.period.localeCompare(a.period) || a.metric.localeCompare(b.metric));
}

function LedgerEmpty({ doc }: { doc: ResearchDoc }) {
  const text =
    doc.status === "no_transcripts"
      ? "screener.in lists no earnings-call transcripts for this company, so there are no promises to check. The numbers above still come straight from its reported results."
      : doc.status === "no_promises"
        ? `No measurable guidance was found in ${doc.transcripts.filter((t) => !t.error).length} call transcripts. Some companies, banks especially, guide in words rather than numbers.`
        : doc.status === "numbers_only"
          ? "This run read the transcripts but did not ask a model to extract promises."
          : "No promises.";
  return <p className={s.emptyLine}>{text}</p>;
}

// ---------------------------------------------------------------- numbers

function Numbers({ numbers }: { numbers: NonNullable<ResearchDoc["numbers"]> }) {
  const q = numbers.quarters;
  const last = q[q.length - 1];
  const ytd = numbers.fiscal_year_to_date;
  const marginKey = numbers.layout === "standard" ? "ebit_margin" : null;
  const tiles: { label: string; value: React.ReactNode; sub: string }[] = [];
  if (last) {
    tiles.push({ label: "Revenue YoY", value: <Delta value={last.revenue_yoy} digits={1} />, sub: last.fiscal });
    tiles.push({ label: "Net profit YoY", value: <Delta value={last.net_profit_yoy} digits={1} />, sub: last.fiscal });
    if (marginKey && last.ebit_margin != null) tiles.push({ label: "EBIT margin", value: <span className="num">{last.ebit_margin.toFixed(1)}%</span>, sub: last.fiscal });
    if (numbers.layout === "lender" && last.gross_npa_pct != null) tiles.push({ label: "Gross NPA", value: <span className="num">{last.gross_npa_pct}%</span>, sub: last.fiscal });
  }
  const ytdRev = ytd?.metrics.revenue_growth;
  if (ytdRev) tiles.push({ label: `Revenue YoY, ${ytd!.period} so far`, value: <Delta value={ytdRev.value} digits={1} />, sub: `${ytdRev.quarters.length} of 4 quarters` });

  return (
    <section className={s.section}>
      <h2 className={s.sectionHead}>Numbers</h2>
      <p className={s.note}>
        From screener.in ({numbers.basis}), computed in Python. ₹ crore; rupee growth, not constant currency.
      </p>
      <div className={s.tiles}>
        {tiles.slice(0, 4).map((t) => (
          <div key={t.label} className={s.tile}>
            <span className={s.tileLabel}>{t.label}</span>
            <span className={s.tileValue}>{t.value}</span>
            <span className={s.tileSub}>{t.sub}</span>
          </div>
        ))}
      </div>
      <div className={s.tableWrap}>
        <table className={s.table}>
          <thead>
            <tr>
              <th scope="col">Quarter</th>
              <th scope="col">Revenue</th>
              <th scope="col">YoY</th>
              <th scope="col">{marginKey ? "EBIT %" : "Profit YoY"}</th>
            </tr>
          </thead>
          <tbody>
            {[...q].reverse().slice(0, 6).map((r) => (
              <tr key={r.period}>
                <th scope="row">{r.fiscal}</th>
                <td className="num">{amount(r.revenue)}</td>
                <td className="num">{pct(r.revenue_yoy, 1)}</td>
                <td className="num">{marginKey ? (r.ebit_margin != null ? `${r.ebit_margin.toFixed(1)}%` : "–") : pct(r.net_profit_yoy, 1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- one promise

function Entry({ e }: { e: LedgerEntry }) {
  // Python gives every entry a label of five words or fewer; older files fall back here.
  const title = e.short_label || (e.metric === "other" ? e.metric_text || "Other promise" : e.metric_label);
  const screener = e.evidence.find((x) => x.kind === "screener") as (LedgerEntry["evidence"][number] & { kind: "screener" }) | undefined;
  return (
    <article className={s.entry}>
      <div className={s.entryHead}>
        <div>
          <h3 className={s.entryTitle}>{title}</h3>
          <p className={s.entryMeta}>
            {e.period === "unspecified" ? "No period stated" : e.period === "medium_term" ? "Medium term" : e.period}
            {e.scope && e.scope !== "company" && (
              <>
                <Sep />
                for {e.scope}
              </>
            )}
            <Sep />
            {e.period_status}
            {e.target.text && (
              <>
                <Sep />
                target <span className="num">{e.target.text}</span>
                {e.target.basis !== "unspecified" && ` (${e.target.basis.replace("_", " ")})`}
              </>
            )}
          </p>
        </div>
        <span className={s.verdict} data-tone={VERDICT_TONE[e.verdict]}>
          {e.verdict}
        </span>
      </div>

      {e.chart && (
        <figure className={s.chart}>
          <Timeline chart={e.chart} label={title} />
          {e.chart.actual && <figcaption>{e.chart.actual.label}</figcaption>}
        </figure>
      )}

      <p className={s.rationale}>{e.rationale}</p>
      {e.revision_path && !e.rationale.includes(e.revision_path) && (
        <p className={s.path}>
          Target {e.revision_direction ?? "changed"}: <span className="num">{e.revision_path}</span>
        </p>
      )}

      <ol className={s.quotes}>
        {e.statements.map((st) => (
          <li key={st.id}>
            <blockquote>&ldquo;{st.quote}&rdquo;</blockquote>
            <p className={s.cite}>
              {st.speaker}
              <Sep />
              {st.call_label ?? st.call}
              <Sep />
              <a href={st.source_url} target="_blank" rel="noopener noreferrer">
                Transcript <ExternalLink size={12} strokeWidth={2} aria-hidden="true" />
              </a>
            </p>
          </li>
        ))}
        {e.actual_quote && (
          <li className={s.actualQuote}>
            <span className={s.actualTag}>Stated actual{e.actual_quote.found_by === "python" ? " · from the year-end call" : ""}</span>
            <blockquote>&ldquo;{e.actual_quote.text}&rdquo;</blockquote>
            <p className={s.cite}>
              {e.actual_quote.speaker}
              <Sep />
              {e.actual_quote.call}
              <Sep />
              <a href={e.actual_quote.source_url} target="_blank" rel="noopener noreferrer">
                Transcript <ExternalLink size={12} strokeWidth={2} aria-hidden="true" />
              </a>
            </p>
          </li>
        )}
      </ol>

      {(screener || e.notes.length > 0) && (
        <details className={s.how}>
          <summary>How this was checked</summary>
          <ul>
            {screener && (
              <li>
                {screener.label}: <span className="num">{screener.value}%</span> ({screener.source})
              </li>
            )}
            {e.statements.map((st) => (
              <li key={`m-${st.id}`}>
                Quote from {st.call} matched the transcript at <span className="num">{st.quote_score}</span>/100.
              </li>
            ))}
            <li>Verdict by {e.verdict_by === "rules" ? "Python rules" : e.verdict_by}.</li>
            {e.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </details>
      )}
    </article>
  );
}

// ---------------------------------------------------------------- sources

function Sources({ doc }: { doc: ResearchDoc }) {
  return (
    <section className={s.section}>
      <h2 className={s.sectionHead}>Sources</h2>
      <ul className={s.sources}>
        {doc.numbers?.source.url && (
          <li>
            <a href={doc.numbers.source.url} target="_blank" rel="noopener noreferrer">
              {doc.numbers.source.name} <ExternalLink size={12} strokeWidth={2} aria-hidden="true" />
            </a>
            <span className={s.sourceMeta}>quarterly and annual results</span>
          </li>
        )}
        {doc.transcripts.map((t) => (
          <li key={t.url}>
            <a href={t.url} target="_blank" rel="noopener noreferrer">
              {t.label ?? t.call} <ExternalLink size={12} strokeWidth={2} aria-hidden="true" />
            </a>
            <span className={s.sourceMeta}>
              {t.error ? t.error.split(":")[0] : `${t.sent} of ${t.passages} passages read by the model · ${t.promises} promises`}
            </span>
          </li>
        ))}
      </ul>
      {doc.dropped.length > 0 && (
        <details className={s.how}>
          <summary>{doc.dropped.length} extracted promise{doc.dropped.length === 1 ? "" : "s"} rejected by the checks</summary>
          <ul>
            {doc.dropped.map((d, i) => (
              <li key={i}>
                {d.call}: {d.reason}. &ldquo;{d.quote}&rdquo;
              </li>
            ))}
          </ul>
        </details>
      )}
      <p className={s.note}>Snapshot built {day(doc.generated_at)}. Not investment advice.</p>
    </section>
  );
}
