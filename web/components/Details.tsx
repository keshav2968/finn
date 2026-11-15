"use client";

import Link from "next/link";
import { Check, ChevronRight, CircleHelp, ExternalLink, MessageCircleQuestion, TriangleAlert } from "lucide-react";
import { amount, croreShort, day, dayTime, direction, longDate, pct, pp, rupees, signed, times } from "@/lib/format";
import { alertReasons, askQuestions, resultsHeadlines, sparkValues } from "@/lib/present";
import type { Card, InboxData, ManagementCard, PriceAlert, ResultsCard, ResultsMetric } from "@/lib/types";
import Delta from "./Delta";
import Spark from "./Spark";
import s from "./sheet.module.css";

function Sep() {
  return (
    <span className="sep" aria-hidden="true">
      ·
    </span>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className={s.fact}>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

// ---------------------------------------------------------------- ask (research comes next)

function Ask({ symbol, questions }: { symbol: string; questions: string[] }) {
  if (!questions.length) return null;
  return (
    <section className={s.section}>
      <h3>Ask Finn</h3>
      <div className={s.asks}>
        {questions.map((q) => (
          <Link key={q} className={s.ask} href={`/research/${encodeURIComponent(symbol)}?q=${encodeURIComponent(q)}`}>
            <MessageCircleQuestion size={16} strokeWidth={1.75} aria-hidden="true" />
            <span>{q}</span>
          </Link>
        ))}
      </div>
      <Link className={s.researchLink} href={`/research/${encodeURIComponent(symbol)}`}>
        Promises vs delivery for this company <ChevronRight size={15} strokeWidth={2} aria-hidden="true" />
      </Link>
    </section>
  );
}

// ---------------------------------------------------------------- price alert

export function PriceDetail({ alert, data }: { alert: PriceAlert; data: InboxData }) {
  const series = data.prices[alert.symbol];
  const values = sparkValues(series, alert.date, series?.date.length ?? 0);
  const avgWindow = series?.volume_avg_window ?? 20;
  const questions = askQuestions(data.ask, "price_alert", {
    name: alert.name,
    symbol: alert.symbol,
    change: pct(alert.pct_change, 1),
    date: day(alert.date),
  });
  return (
    <>
      <h2 className={s.title}>
        {alert.name} <span className={`ticker ${s.titleTicker}`}>{alert.symbol}</span>
      </h2>
      <p className={s.sub}>Price alert · {day(alert.date)} close</p>

      <div className={s.hero}>
        <span className={`num ${s.heroValue}`}>{rupees(alert.close)}</span>
        <Delta value={alert.pct_change} />
      </div>
      {values.length > 1 && (
        <figure className={s.chart}>
          <Spark values={values} width={320} height={84} dir={direction(alert.pct_change)} fluid />
          <figcaption>
            Closing price, {values.length} sessions to {day(alert.date)}
          </figcaption>
        </figure>
      )}

      <section className={s.section}>
        <h3>Why it fired</h3>
        <ul className={s.reasons}>
          {alertReasons(alert, avgWindow).map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
        <dl className={s.facts}>
          <Fact label={`Volume vs ${avgWindow}-day avg`}>{times(alert.vol_ratio)}</Fact>
          <Fact label="Swing vs its usual day">{alert.move_z === null ? "–" : `${Math.abs(alert.move_z).toFixed(1)}×`}</Fact>
        </dl>
      </section>

      <Ask symbol={alert.symbol} questions={questions} />
    </>
  );
}

// ---------------------------------------------------------------- filing card

export function FilingDetail({ card, data }: { card: Card; data: InboxData }) {
  const { lead } = card;
  const name = data.companies[lead.symbol]?.name ?? lead.symbol;
  const results = card.results_symbol ? data.results[card.results_symbol] : undefined;
  const heads = resultsHeadlines(card, data);
  const person = card.management?.people.find((p) => p.direction !== "continuing") ?? card.management?.people[0];
  const category = results ? "results" : lead.category;
  const questions = askQuestions(data.ask, category, {
    name,
    symbol: lead.symbol,
    metric: heads[0]?.label,
    change: heads[0] ? pct(heads[0].yoy, 1) : null,
    person: person?.name,
  });

  return (
    <>
      <h2 className={s.title}>
        {name} <span className={`ticker ${s.titleTicker}`}>{lead.symbol}</span>
      </h2>
      <p className={s.sub}>
        {lead.category_label}
        <Sep />
        {dayTime(lead.datetime)}
      </p>
      <p className={s.headline}>{lead.headline}</p>

      {heads.length > 0 && (
        <div className={s.heroFigures}>
          {heads.map((h, i) => (
            <div key={h.label} className={s.heroFigure}>
              <span className={s.heroLabel}>
                {h.label}, {results?.periods.current}
              </span>
              <span className={`num ${i === 0 ? s.heroValue : s.heroValueSmall}`}>{croreShort(h.value)}</span>
              <Delta value={h.yoy} digits={1} suffix="YoY" />
            </div>
          ))}
        </div>
      )}

      {card.management && <People mgmt={card.management} />}
      {results && <ResultsTable card={results} />}

      {lead.reaction && lead.reaction.pct_change !== null && (
        <section className={s.section}>
          <h3>Stock reaction</h3>
          <dl className={s.facts}>
            <Fact label={`Move on ${day(lead.reaction.date)}`}>
              <Delta value={lead.reaction.pct_change} />
            </Fact>
            <Fact label="Volume vs average">{times(lead.reaction.vol_ratio)}</Fact>
          </dl>
        </section>
      )}

      <section className={s.section}>
        <h3>Why it ranks here</h3>
        <ul className={s.parts}>
          {lead.score_parts.map((p, i) => (
            <li key={`${p.label}-${i}`}>
              <span>{p.label}</span>
              <span>{signed(p.delta, 0)}</span>
            </li>
          ))}
          <li className={s.total}>
            <span>
              {data.tier_labels[lead.tier]}
              <span className={s.muted}>
                {" "}
                · {data.tier_labels.needs_attention} from {data.tiers.needs_attention}, {data.tier_labels.worth_knowing.toLowerCase()} from{" "}
                {data.tiers.worth_knowing}
              </span>
            </span>
            <span>{Math.round(lead.score)}</span>
          </li>
        </ul>
      </section>

      {card.members.length > 1 && (
        <section className={s.section}>
          <h3>Filings in this card · {card.members.length}</h3>
          <ul className={s.related}>
            {card.members.map((m) => (
              <li key={m.id}>
                <span className={s.relatedText}>{m.headline}</span>
                <span className={s.relatedMeta}>
                  <span>{dayTime(m.datetime)}</span>
                  {m.pdf_url && (
                    <a href={m.pdf_url} target="_blank" rel="noopener noreferrer">
                      Filing <ExternalLink size={13} strokeWidth={1.75} aria-hidden="true" />
                    </a>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <Ask symbol={lead.symbol} questions={questions} />
    </>
  );
}

// ---------------------------------------------------------------- results

const STATUS_TEXT: Record<ResultsCard["status"], string> = {
  verified: "Every figure checks out against the statement's own totals and screener.in.",
  partial: "Some figures couldn't be checked; the rest match.",
  mismatch: "Some figures don't match screener.in. They're flagged, with screener's figure underneath; figures marked ? couldn't be checked.",
  screener_only: "The filing couldn't be read, so these figures are from screener.in.",
  unavailable: "No results card for this quarter.",
};

function CheckMark({ m }: { m: ResultsMetric }) {
  const c = m.check.current;
  if (c === "verified") return <Check size={14} strokeWidth={2.25} aria-label="Checked" className={s.checkOk} />;
  if (c === "mismatch") return <TriangleAlert size={14} strokeWidth={2} aria-label="Doesn't match screener.in" className={s.checkBad} />;
  if (c === "screener") return <span className={s.src} aria-label="From screener.in">s</span>;
  // Read off the filing but not confirmed by the statement's totals or screener.in.
  if (c === "unchecked") return <CircleHelp size={14} strokeWidth={2} aria-label="Not checked" className={s.checkUnknown} />;
  return null;
}

function change(m: ResultsMetric, v: number | null) {
  return m.kind === "margin" ? pp(v) : pct(v, 1);
}

function value(m: ResultsMetric, v: number | null | undefined) {
  if (v === null || v === undefined) return "–";
  return m.kind === "margin" ? `${v.toFixed(1)}%` : amount(v);
}

export function ResultsTable({ card }: { card: ResultsCard }) {
  return (
    <section className={s.section}>
      <h3>
        Results · {card.periods.current} quarter · {card.basis}
      </h3>
      <p className={s.note}>{STATUS_TEXT[card.status]}</p>
      <div className={s.tableWrap}>
        <table className={s.table}>
          <thead>
            <tr>
              <th scope="col">₹ crore</th>
              <th scope="col">{card.periods.current}</th>
              <th scope="col">QoQ</th>
              <th scope="col">YoY</th>
            </tr>
          </thead>
          <tbody>
            {card.metrics.map((m) => (
              <tr key={m.key} data-minor={!m.main || undefined}>
                <th scope="row">
                  <span className={s.metricLabel}>
                    {m.label}
                    <CheckMark m={m} />
                  </span>
                  {m.check.current === "mismatch" && m.screener.current != null && (
                    <span className={s.screener}>screener.in {value(m, m.screener.current)}</span>
                  )}
                </th>
                <td className="num">{value(m, m.current)}</td>
                <td className="num">{change(m, m.qoq)}</td>
                <td className="num">{change(m, m.yoy)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {(card.notes.length > 0 || card.formula) && (
        <details className={s.notes}>
          <summary>How these were checked</summary>
          <ul>
            {card.formula && <li>{card.formula}</li>}
            {card.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- management

const DIRECTION: Record<string, string> = { joining: "Joining", leaving: "Leaving", continuing: "Continuing" };

export function People({ mgmt }: { mgmt: ManagementCard }) {
  return (
    <section className={s.section}>
      <h3>People</h3>
      <p className={s.lead}>{mgmt.summary}</p>
      <ul className={s.people}>
        {mgmt.people.map((p, i) => (
          <li key={`${p.name}-${i}`}>
            <div className={s.personHead}>
              <span className={s.personName}>{p.name}</span>
              <span className={s.direction} data-dir={p.direction}>
                {DIRECTION[p.direction] ?? p.direction}
              </span>
            </div>
            <p className={s.personRole}>
              {p.role}
              {p.at_subsidiary && p.entity ? ` at ${p.entity}` : ""}
            </p>
            {p.flags.length > 0 && (
              <div className={s.tags}>
                {p.flags.map((f) => (
                  <span key={f.code} className={s.tag} data-strong={f.code === "ceo_exit" || f.code === "cfo_exit" || undefined}>
                    {f.label}
                  </span>
                ))}
              </div>
            )}
            <dl className={s.personFacts}>
              {p.effective_date && (
                <div>
                  <dt>Effective</dt>
                  <dd>{longDate(p.effective_date)}</dd>
                </div>
              )}
              {p.tenure && (
                <div>
                  <dt>Term</dt>
                  <dd>{p.tenure}</dd>
                </div>
              )}
              {p.stated_reason && (
                <div>
                  <dt>Stated reason</dt>
                  <dd>{p.stated_reason}</dd>
                </div>
              )}
              {p.prior_roles.length > 0 && (
                <div>
                  <dt>Before this</dt>
                  <dd>{p.prior_roles.join("; ")}</dd>
                </div>
              )}
            </dl>
          </li>
        ))}
      </ul>
      {mgmt.notes.length > 0 && <p className={s.note}>{mgmt.notes.join(" ")}</p>}
    </section>
  );
}
