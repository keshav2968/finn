"use client";

import { ArrowDown, ArrowUp, Check, ExternalLink, TriangleAlert } from "lucide-react";
import { amount, day, dayTime, direction, longDate, pct, pp, price, signed, times } from "@/lib/format";
import { alertReason, sparkValues } from "@/lib/present";
import type { Card, InboxData, ManagementCard, PriceAlert, ResultsCard, ResultsMetric } from "@/lib/types";
import Spark from "./Spark";
import s from "./sheet.module.css";

/** Price movement: green/red, always with an arrow and a sign. */
export function Move({ value, digits = 2, className }: { value: number | null; digits?: number; className?: string }) {
  const dir = direction(value);
  const Icon = dir === "up" ? ArrowUp : dir === "down" ? ArrowDown : null;
  return (
    <span className={`num ${className ?? ""}`} data-move={dir}>
      {Icon && <Icon size="0.9em" strokeWidth={2.25} aria-hidden="true" style={{ verticalAlign: "-0.08em", marginRight: 2 }} />}
      {pct(value, digits)}
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

// ---------------------------------------------------------------- price alert

export function PriceDetail({ alert, data }: { alert: PriceAlert; data: InboxData }) {
  const series = data.prices[alert.symbol];
  const values = sparkValues(series, alert.date, series?.date.length ?? 0);
  const avgWindow = series?.volume_avg_window ?? 20;
  return (
    <>
      <p className={s.meta}>
        <span className="num">{alert.symbol}</span><span className="sep" aria-hidden="true">·</span>Price alert<span className="sep" aria-hidden="true">·</span>{day(alert.date)} close
      </p>
      <h2 className={s.title}>{alert.name}</h2>

      <div className={s.hero}>
        <span className={`num ${s.heroValue}`}>{price(alert.close)}</span>
        <Move value={alert.pct_change} className={s.heroMove} />
      </div>
      {values.length > 1 && (
        <figure className={s.chart}>
          <Spark values={values} width={320} height={72} dir={direction(alert.pct_change)} fluid />
          <figcaption>
            {values.length} sessions to {day(alert.date)}
          </figcaption>
        </figure>
      )}

      <section className={s.section}>
        <h3>Why it fired</h3>
        <p className={s.lead}>{alertReason(alert, data.rules, avgWindow)}</p>
        <dl className={s.facts}>
          <Fact label="Day move">
            <Move value={alert.pct_change} />
          </Fact>
          <Fact label={`Volume vs ${avgWindow}-day avg`}>
            <span className="num">{times(alert.vol_ratio)}</span>
          </Fact>
          <Fact label="Swing vs its usual day">
            <span className="num">{alert.move_z === null ? "–" : `${Math.abs(alert.move_z).toFixed(1)}×`}</span>
          </Fact>
        </dl>
      </section>
    </>
  );
}

// ---------------------------------------------------------------- filing card

export function FilingDetail({ card, data }: { card: Card; data: InboxData }) {
  const { lead } = card;
  const name = data.companies[lead.symbol]?.name ?? lead.symbol;
  const results = card.results_symbol ? data.results[card.results_symbol] : undefined;
  return (
    <>
      <p className={s.meta}>
        <span className="num">{lead.symbol}</span><span className="sep" aria-hidden="true">·</span>{name}
      </p>
      <h2 className={s.title}>{lead.headline}</h2>
      <p className={s.sub}>
        {lead.category_label}<span className="sep" aria-hidden="true">·</span><span className="num">{dayTime(lead.datetime)}</span>
      </p>

      {card.management && <People mgmt={card.management} />}
      {results && <ResultsTable card={results} />}

      {lead.reaction && lead.reaction.pct_change !== null && (
        <section className={s.section}>
          <h3>Stock reaction</h3>
          <dl className={s.facts}>
            <Fact label={`Move on ${day(lead.reaction.date)}`}>
              <Move value={lead.reaction.pct_change} />
            </Fact>
            <Fact label="Volume vs average">
              <span className="num">{times(lead.reaction.vol_ratio)}</span>
            </Fact>
          </dl>
        </section>
      )}

      <section className={s.section}>
        <h3>Why it ranks here</h3>
        <ul className={s.parts}>
          {lead.score_parts.map((p, i) => (
            <li key={`${p.label}-${i}`}>
              <span>{p.label}</span>
              <span className="num">{signed(p.delta, 0)}</span>
            </li>
          ))}
          <li className={s.total}>
            <span>
              {data.tier_labels[lead.tier]}
              <span className={s.muted}>
                {" "}
                · {data.tier_labels.needs_attention} from <span className="num">{data.tiers.needs_attention}</span>,{" "}
                {data.tier_labels.worth_knowing.toLowerCase()} from <span className="num">{data.tiers.worth_knowing}</span>
              </span>
            </span>
            <span className="num">{Math.round(lead.score)}</span>
          </li>
        </ul>
      </section>

      {card.members.length > 1 && (
        <section className={s.section}>
          <h3>
            Filings in this card <span className={`num ${s.muted}`}>{card.members.length}</span>
          </h3>
          <ul className={s.related}>
            {card.members.map((m) => (
              <li key={m.id}>
                <span className={s.relatedText}>{m.headline}</span>
                <span className={s.relatedMeta}>
                  <span className="num">{dayTime(m.datetime)}</span>
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
    </>
  );
}

// ---------------------------------------------------------------- results

const STATUS_TEXT: Record<ResultsCard["status"], string> = {
  verified: "Every figure checks out against the statement's own totals and screener.in.",
  partial: "Some figures couldn't be checked; the rest match.",
  mismatch: "Some figures don't match screener.in. They're marked, with screener's figure underneath.",
  screener_only: "The filing couldn't be read, so these figures are from screener.in.",
  unavailable: "No results card for this quarter.",
};

function CheckMark({ m }: { m: ResultsMetric }) {
  const c = m.check.current;
  if (c === "verified") return <Check size={14} strokeWidth={2} aria-label="Checked" className={s.checkOk} />;
  if (c === "mismatch") return <TriangleAlert size={14} strokeWidth={2} aria-label="Doesn't match screener.in" />;
  if (c === "screener") return <span className={s.src} aria-label="From screener.in">s</span>;
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
        Results<span className="sep" aria-hidden="true">·</span>{card.periods.current} quarter <span className={s.muted}><span className="sep" aria-hidden="true">·</span>{card.basis}</span>
      </h3>
      <p className={s.note}>{STATUS_TEXT[card.status]}</p>
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
                  <span className={s.screener}>
                    screener.in <span className="num">{value(m, m.screener.current)}</span>
                  </span>
                )}
              </th>
              <td className="num">{value(m, m.current)}</td>
              <td className="num">{change(m, m.qoq)}</td>
              <td className="num">{change(m, m.yoy)}</td>
            </tr>
          ))}
        </tbody>
      </table>
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
              <span className={s.muted}>{DIRECTION[p.direction] ?? p.direction}</span>
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
                  <dd className="num">{longDate(p.effective_date)}</dd>
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
