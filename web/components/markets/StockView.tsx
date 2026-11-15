"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { ChevronLeft, ChevronRight, ScanSearch } from "lucide-react";
import { buildCards } from "@/lib/inbox";
import { day, dayTime, pct, rupees, shares, times, weekday } from "@/lib/format";
import type { Quote, StockSeries } from "@/lib/data";
import type { Card, InboxData } from "@/lib/types";
import Delta from "../Delta";
import FilingSheet, { type Opened } from "../news/FilingSheet";
import { storyHeadline } from "../news/story";
import { useReadState } from "../news/NewsFeed";
import PriceChart, { type Marker } from "./PriceChart";
import u from "../ui.module.css";
import s from "./markets.module.css";

export interface ResearchLink {
  status: string;
  text: string | null;
}

export default function StockView({
  quote,
  series,
  data,
  research,
}: {
  quote: Quote;
  series: StockSeries;
  data: InboxData; // this company's filings only
  research: ResearchLink | null;
}) {
  const [open, setOpen] = useState<Opened>(null);
  const [read, setRead] = useReadState();
  const [showRoutine, setShowRoutine] = useState(false);

  const cards: Card[] = useMemo(
    () => buildCards(data.items, data.same_day_categories).map((c) => ({ ...c, alert: false })).sort((a, b) => b.lead.datetime.localeCompare(a.lead.datetime)),
    [data],
  );
  const notable = cards.filter((c) => c.lead.tier !== "routine");
  const routine = cards.filter((c) => c.lead.tier === "routine");
  const markers: Marker[] = notable.map((c) => ({
    id: c.key,
    date: c.lead.reaction?.date ?? c.lead.datetime.slice(0, 10),
    tier: c.lead.tier,
    label: storyHeadline(c, data),
  }));
  const openCard = (c: Card) => {
    setOpen({ type: "card", card: c });
    if (!(c.key in read)) setRead((prev) => ({ ...prev, [c.key]: new Date().toISOString() }));
  };

  const r = quote.returns_pct;
  const lo = quote.low_52w;
  const hi = quote.high_52w;
  const at = lo !== null && hi !== null && hi > lo ? ((quote.close - lo) / (hi - lo)) * 100 : null;
  const firstFiling = data.items.reduce((m, it) => (it.datetime < m ? it.datetime : m), "9999");

  return (
    <div className={u.page}>
      <nav className={s.back}>
        <Link href="/markets" className={s.backLink}>
          <ChevronLeft size={18} strokeWidth={2} aria-hidden="true" /> Markets
        </Link>
      </nav>

      <header>
        <p className={s.kicker}>
          <span className="ticker">{quote.symbol}</span>
          {quote.sector && ` · ${quote.sector}`}
          {quote.size && ` · ${quote.size} cap`}
        </p>
        <h1 className={s.stockName}>{quote.name}</h1>
        <div className={s.priceHero}>
          <span className={`num ${s.bigPrice}`}>{rupees(quote.close)}</span>
          <Delta value={quote.pct_change} />
        </div>
        <p className={u.sub}>
          {weekday(quote.as_of)} close
          {quote.prev_close !== null && ` · previous ${rupees(quote.prev_close)}`}
        </p>
      </header>

      <PriceChart
        series={series}
        markers={markers}
        onMarker={(id) => {
          const c = cards.find((x) => x.key === id);
          if (c) openCard(c);
        }}
      />

      <section className={u.section} aria-labelledby="stats">
        <h2 id="stats" className={u.sectionHead}>
          {weekday(quote.as_of)} session
        </h2>
        <dl className={s.stats}>
          <div>
            <dt>Volume</dt>
            <dd className="num">{shares(quote.volume)}</dd>
            <dd className={s.statSub}>{quote.vol_ratio !== null ? `${times(quote.vol_ratio)} its 20-day average` : "–"}</dd>
          </div>
          <div>
            <dt>Size of the move</dt>
            <dd className="num">{quote.move_z !== null ? `${Math.abs(quote.move_z).toFixed(1)}σ` : "–"}</dd>
            <dd className={s.statSub}>In standard deviations of its last 60 daily moves</dd>
          </div>
          <div className={s.statWide}>
            <dt>52-week range</dt>
            <dd className={s.range52}>
              <span className="num">{rupees(lo)}</span>
              <span className={s.rangeTrack} aria-hidden="true">
                {at !== null && <span className={s.rangeDot} style={{ left: `${at}%` }} />}
              </span>
              <span className="num">{rupees(hi)}</span>
            </dd>
          </div>
        </dl>
        <div className={s.returns} role="list" aria-label="Returns">
          {(["1w", "1m", "3m", "6m", "1y"] as const).map((k) => (
            <span key={k} role="listitem" className={s.ret}>
              <span className={s.retLabel}>{k.toUpperCase()}</span>
              <Delta value={r[k] ?? null} digits={1} />
            </span>
          ))}
        </div>
      </section>

      <section className={u.section} aria-labelledby="filings">
        <h2 id="filings" className={u.sectionHead}>
          Filings <span>since {firstFiling !== "9999" ? day(firstFiling) : "–"}</span>
        </h2>
        {notable.length === 0 ? (
          <p className={u.sub}>No filings above routine in the snapshot.</p>
        ) : (
          <ul className={s.filings}>
            {notable.map((c) => (
              <li key={c.key}>
                <button type="button" className={`${s.filing} row`} data-read={c.key in read || undefined} onClick={() => openCard(c)}>
                  <span className={s.filingTop}>
                    <span className={s.tierDot} data-tier={c.lead.tier} />
                    <span className={s.filingImpact}>{data.tier_labels[c.lead.tier]}</span>
                    <span>{dayTime(c.lead.datetime)}</span>
                  </span>
                  <span className={s.filingHead}>{storyHeadline(c, data)}</span>
                  <span className={s.filingMeta}>
                    {c.lead.category_label}
                    {c.lead.reaction?.pct_change != null && ` · stock ${pct(c.lead.reaction.pct_change, 1)} on ${day(c.lead.reaction.date)}`}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
        {routine.length > 0 && (
          <>
            <button type="button" className={u.textButton} onClick={() => setShowRoutine((v) => !v)} aria-expanded={showRoutine}>
              {showRoutine ? "Hide" : "Show"} {routine.length} routine filings
            </button>
            {showRoutine && (
              <ul className={s.filings}>
                {routine.map((c) => (
                  <li key={c.key}>
                    <button type="button" className={`${s.filing} row`} data-read={c.key in read || undefined} onClick={() => openCard(c)}>
                      <span className={s.filingHead} style={{ fontWeight: 500 }}>
                        {c.lead.headline}
                      </span>
                      <span className={s.filingMeta}>
                        {c.lead.category_label} · {day(c.lead.datetime)}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </section>

      <Link href={`/research/${quote.symbol}`} className={`${s.researchCard} row`}>
        <ScanSearch size={22} strokeWidth={1.75} aria-hidden="true" />
        <span>
          <strong>Promises vs delivery</strong>
          <span>{research ? (research.text ?? "Numbers from screener.in") : "Not researched yet. The page shows the command that builds it."}</span>
        </span>
        <ChevronRight size={18} strokeWidth={2} aria-hidden="true" />
      </Link>

      <FilingSheet open={open} data={data} onClose={() => setOpen(null)} hideChartLink />
    </div>
  );
}
