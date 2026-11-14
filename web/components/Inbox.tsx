"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { alertKeys, buildInbox } from "@/lib/inbox";
import { crore, day, dayTime, direction, pct, plural, price, times } from "@/lib/format";
import type { Card, InboxData, PriceAlert } from "@/lib/types";
import { BellIcon, CheckIcon, ChevronIcon, ExternalIcon, MoonIcon, SunIcon, Tri } from "./Icons";
import { useStored } from "./useStored";
import s from "./inbox.module.css";

type Done = Record<string, string>; // key -> when it was marked done
type Toast = { key: string; label: string } | null;

export default function Inbox({ data }: { data: InboxData }) {
  const [windowKey, setWindowKey] = useStored<string>("finn.window", data.default_window);
  const [done, setDone] = useStored<Done>("finn.done.v1", {});
  const [alertsOnly, setAlertsOnly] = useState(false);
  const [routineOpen, setRoutineOpen] = useState(false);
  const [doneOpen, setDoneOpen] = useState(false);
  const [toast, setToast] = useState<Toast>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const win = data.windows.find((w) => w.key === windowKey) ?? data.windows.find((w) => w.key === data.default_window)!;
  const view = useMemo(() => buildInbox(data, win.hours), [data, win.hours]);
  const alerts = useMemo(() => new Set(alertKeys(view)), [view]);

  const isDone = (key: string) => key in done;
  const pick = (cards: Card[]) => cards.filter((c) => !alertsOnly || c.alert);

  const priceList = view.priceAlerts;
  const needs = pick(view.needs);
  const worth = pick(view.worth);
  const openPrice = priceList.filter((a) => !isDone(a.key));
  const openNeeds = needs.filter((c) => !isDone(c.key));
  const openWorth = worth.filter((c) => !isDone(c.key));
  const doneRows: { key: string; symbol: string; text: string }[] = [
    ...priceList.filter((a) => isDone(a.key)).map((a) => ({ key: a.key, symbol: a.symbol, text: a.reasons.join(" · ") })),
    ...[...needs, ...worth].filter((c) => isDone(c.key)).map((c) => ({ key: c.key, symbol: c.lead.symbol, text: c.lead.headline })),
  ];
  const toReview = openPrice.length + openNeeds.length + openWorth.length;
  const total = toReview + doneRows.length;
  const badge = [...alerts].filter((k) => !isDone(k)).length;

  function mark(key: string, label: string) {
    setDone((prev) => ({ ...prev, [key]: new Date().toISOString() }));
    setToast({ key, label });
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 4000);
  }

  function unmark(key: string) {
    setDone((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
    setToast((t) => (t?.key === key ? null : t));
  }

  useEffect(() => () => {
    if (toastTimer.current) clearTimeout(toastTimer.current);
  }, []);

  const wider = data.windows.find((w) => w.hours > win.hours);
  const routineFilings = view.routine.reduce((n, c) => n + c.members.length, 0);

  return (
    <div className={s.app}>
      <header className={s.header}>
        <div className={s.brandRow}>
          <div>
            <div className={s.brand}>FINN</div>
            <div className={s.snapshot}>
              Snapshot {dayTime(data.snapshot_at)} IST
              {data.prices_as_of ? ` · prices to ${day(data.prices_as_of)} close` : ""}
            </div>
          </div>
          <div className={s.actions}>
            <ThemeToggle />
            <button
              type="button"
              className={s.iconButton}
              aria-pressed={alertsOnly}
              aria-label={`${alertsOnly ? "Show everything" : "Show alerts only"}, ${plural(badge, "new alert")}`}
              onClick={() => setAlertsOnly((v) => !v)}
              data-active={alertsOnly || undefined}
            >
              <BellIcon />
              {badge > 0 && <span className={s.badge}>{badge}</span>}
            </button>
          </div>
        </div>

        <div className={s.chipRow}>
          <div className={s.chips} role="group" aria-label="Time window">
            {data.windows.map((w) => (
              <button
                key={w.key}
                type="button"
                className={s.chip}
                aria-pressed={w.key === win.key}
                onClick={() => setWindowKey(w.key)}
              >
                {w.label}
              </button>
            ))}
          </div>
          <span className={s.range}>
            {day(view.from)} – {day(view.to)}
          </span>
        </div>
      </header>

      <main className={s.main}>
        <section className={s.summary} aria-live="polite">
          <div className={s.count}>
            <span className={s.big}>{toReview}</span>
            <span>{alertsOnly ? "alerts to review" : "to review"}</span>
          </div>
          <div className={s.sub}>
            {doneRows.length} done · {plural(view.filingCount, "filing")} and {plural(priceList.length, "price alert")} in
            this window
          </div>
          <div className={s.progress} role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={doneRows.length}>
            <span style={{ width: total ? `${(100 * doneRows.length) / total}%` : "0%" }} />
          </div>
        </section>

        {alertsOnly && (
          <div className={s.filterBar}>
            <span>Showing alerts only</span>
            <button type="button" className={s.textButton} onClick={() => setAlertsOnly(false)}>
              Show everything
            </button>
          </div>
        )}

        {toReview === 0 && (
          <CaughtUp
            empty={total === 0}
            from={view.from}
            to={view.to}
            note={data.schedule_note}
            wider={wider ? { label: wider.label, onClick: () => setWindowKey(wider.key) } : null}
          />
        )}

        {openPrice.length > 0 && (
          <Section title="Price alerts" count={openPrice.length}>
            {openPrice.map((a) => (
              <PriceRow key={a.key} alert={a} onDone={() => mark(a.key, `${a.symbol} price alert`)} />
            ))}
          </Section>
        )}

        {openNeeds.length > 0 && (
          <Section title={data.tier_labels.needs_attention} count={openNeeds.length}>
            {openNeeds.map((c) => (
              <CardRow key={c.key} card={c} data={data} onDone={() => mark(c.key, `${c.lead.symbol} ${c.lead.category_label.toLowerCase()}`)} />
            ))}
          </Section>
        )}

        {openWorth.length > 0 && (
          <Section title={data.tier_labels.worth_knowing} count={openWorth.length}>
            {openWorth.map((c) => (
              <CardRow key={c.key} card={c} data={data} onDone={() => mark(c.key, `${c.lead.symbol} ${c.lead.category_label.toLowerCase()}`)} />
            ))}
          </Section>
        )}

        {!alertsOnly && view.routine.length > 0 && (
          <section className={s.fold}>
            <button type="button" className={s.foldHead} aria-expanded={routineOpen} onClick={() => setRoutineOpen((v) => !v)}>
              <span>
                <span className={s.foldTitle}>
                  {data.tier_labels.routine} · {plural(routineFilings, "filing")}
                </span>
                <span className={s.foldSub}>{routineMix(view.routine)} · not counted</span>
              </span>
              <ChevronIcon className={s.chev} />
            </button>
            {routineOpen && (
              <ul className={s.compact}>
                {view.routine.map((c) => (
                  <li key={c.key}>
                    <div className={s.compactMeta}>
                      <span className={s.sym}>{c.lead.symbol}</span>
                      <span>{c.lead.category_label}</span>
                      <span className={s.time}>{dayTime(c.lead.datetime)}</span>
                    </div>
                    <div className={s.compactText}>
                      {c.lead.headline}
                      {c.members.length > 1 && <span className={s.muted}> · +{c.members.length - 1} similar</span>}
                      {c.lead.pdf_url && <Pdf url={c.lead.pdf_url} />}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}

        {doneRows.length > 0 && (
          <section className={s.fold}>
            <button type="button" className={s.foldHead} aria-expanded={doneOpen} onClick={() => setDoneOpen((v) => !v)}>
              <span className={s.foldTitle}>Done · {doneRows.length}</span>
              <ChevronIcon className={s.chev} />
            </button>
            {doneOpen && (
              <ul className={s.compact}>
                {doneRows.map((r) => (
                  <li key={r.key} className={s.doneItem}>
                    <span className={s.compactText}>
                      <span className={s.sym}>{r.symbol}</span> {r.text}
                    </span>
                    <button type="button" className={s.textButton} onClick={() => unmark(r.key)}>
                      Undo
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}

        <footer className={s.footer}>
          Filings from BSE, prices from Yahoo Finance (end of day), results checked against screener.in. Scores rank
          what to read first; they are not advice.
        </footer>
      </main>

      {toast && (
        <div className={s.toast} role="status">
          <span>Done: {toast.label}</span>
          <button type="button" onClick={() => unmark(toast.key)}>
            Undo
          </button>
        </div>
      )}
    </div>
  );
}

function Section({ title, count, children }: { title: string; count: number; children: React.ReactNode }) {
  return (
    <section className={s.section}>
      <h2 className={s.sectionHead}>
        <span>{title}</span>
        <span className={s.sectionCount}>{count}</span>
      </h2>
      <div className={s.rows}>{children}</div>
    </section>
  );
}

function DoneButton({ label, onDone }: { label: string; onDone: () => void }) {
  return (
    <button type="button" className={s.doneButton} aria-label={`Mark done: ${label}`} onClick={onDone}>
      <span className={s.doneRing}>
        <CheckIcon />
      </span>
    </button>
  );
}

function Move({ value, suffix = "" }: { value: number | null; suffix?: string }) {
  const dir = direction(value);
  return (
    <span className={s.move} data-dir={dir}>
      <Tri dir={dir} />
      {pct(value)}
      {suffix}
    </span>
  );
}

function PriceRow({ alert, onDone }: { alert: PriceAlert; onDone: () => void }) {
  return (
    <article className={s.row}>
      <div className={s.rowMain}>
        <div className={s.meta}>
          <span className={s.sym}>{alert.symbol}</span>
          <span className={s.name}>{alert.name}</span>
          <span className={s.time}>{day(alert.date)} close</span>
        </div>
        <div className={s.priceLine}>
          <span className={s.close}>{price(alert.close)}</span>
          <span data-hit={alert.triggers.includes("price_move") || undefined} className={s.metric}>
            <Move value={alert.pct_change} />
          </span>
          <span data-hit={alert.triggers.includes("volume_spike") || undefined} className={s.metric}>
            Vol {times(alert.vol_ratio)} avg
          </span>
          {alert.move_z !== null && (
            <span data-hit={alert.triggers.includes("move_z") || undefined} className={s.metric}>
              {Math.abs(alert.move_z).toFixed(1)}σ
            </span>
          )}
        </div>
      </div>
      <DoneButton label={`${alert.symbol} price alert`} onDone={onDone} />
    </article>
  );
}

function CardRow({ card, data, onDone }: { card: Card; data: InboxData; onDone: () => void }) {
  const { lead } = card;
  const name = data.companies[lead.symbol]?.name;
  const reasons = lead.reasons.filter((r) => r !== lead.category_label).slice(0, data.max_reasons);
  const related = card.members.length - 1;
  return (
    <article className={s.row}>
      <div className={s.rowMain}>
        <div className={s.meta}>
          <span className={s.sym}>{lead.symbol}</span>
          {name && <span className={s.name}>{name}</span>}
          <span className={s.time}>{dayTime(lead.datetime)}</span>
        </div>
        <h3 className={s.headline}>{lead.headline}</h3>

        {card.results && card.results.metrics.length > 0 && (
          <div className={s.facts}>
            {card.results.metrics.map((m) => (
              <span key={m.key} className={s.fact}>
                <span className={s.factLabel}>{m.label}</span> {crore(m.current)}
                {m.yoy_pct !== null && <span className={s.muted}> {pct(m.yoy_pct, 1)} YoY</span>}
              </span>
            ))}
            <span className={s.muted}>{card.results.period} qtr</span>
          </div>
        )}

        {card.management && (
          <div className={s.mgmt}>
            {card.management.flags.length > 0 && (
              <div className={s.tags}>
                {card.management.flags.map((f, i) => (
                  <span key={`${f.code}-${i}`} className={s.tag} data-strong={f.code === "ceo_exit" || f.code === "cfo_exit" || undefined}>
                    {f.label}
                  </span>
                ))}
              </div>
            )}
            <p className={s.summaryText}>{card.management.summary}</p>
          </div>
        )}

        {lead.reaction && lead.reaction.pct_change !== null && (
          <div className={s.reaction}>
            <span className={s.muted}>Stock on {day(lead.reaction.date)}</span>
            <Move value={lead.reaction.pct_change} />
            {lead.reaction.vol_ratio !== null && <span className={s.muted}>Vol {times(lead.reaction.vol_ratio)}</span>}
          </div>
        )}

        <div className={s.why}>
          <span className={s.category}>
            {card.alert && <BellIcon size={12} />}
            {lead.category_label}
          </span>
          {reasons.map((r) => (
            <span key={r}>{r}</span>
          ))}
          <span>Score {Math.round(lead.score)}</span>
          {related > 0 && <span>+{related} related</span>}
          {lead.pdf_url && <Pdf url={lead.pdf_url} />}
        </div>
      </div>
      <DoneButton label={`${lead.symbol}: ${lead.headline}`} onDone={onDone} />
    </article>
  );
}

function Pdf({ url }: { url: string }) {
  return (
    <a className={s.pdf} href={url} target="_blank" rel="noopener noreferrer">
      Filing <ExternalIcon />
    </a>
  );
}

function CaughtUp({
  empty,
  from,
  to,
  note,
  wider,
}: {
  empty: boolean;
  from: string;
  to: string;
  note: string;
  wider: { label: string; onClick: () => void } | null;
}) {
  return (
    <section className={s.caught}>
      <span className={s.caughtMark}>
        <CheckIcon size={20} />
      </span>
      <h2>{empty ? "Nothing new in this window" : "You're caught up"}</h2>
      <p>
        {empty ? "No alerts or filings worth reading" : "Everything worth reading"} from {dayTime(from)} to {dayTime(to)}
        {empty ? "." : " is done."} {note}
      </p>
      {wider && (
        <button type="button" className={s.textButton} onClick={wider.onClick}>
          Look back {wider.label}
        </button>
      )}
    </section>
  );
}

function ThemeToggle() {
  const [theme, setTheme] = useState<"light" | "dark">("light");
  useEffect(() => {
    setTheme(document.documentElement.dataset.theme === "dark" ? "dark" : "light");
  }, []);
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button
      type="button"
      className={s.iconButton}
      aria-label={`Switch to ${next} mode`}
      onClick={() => {
        document.documentElement.dataset.theme = next;
        try {
          localStorage.setItem("finn.theme", next); // raw string: read by the pre-paint script in layout.tsx
        } catch {
          /* storage unavailable */
        }
        setTheme(next);
      }}
    >
      {theme === "dark" ? <SunIcon /> : <MoonIcon />}
    </button>
  );
}

function routineMix(cards: Card[]): string {
  const counts = new Map<string, number>();
  for (const c of cards) counts.set(c.lead.category_label, (counts.get(c.lead.category_label) ?? 0) + c.members.length);
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([label]) => label)
    .join(", ");
}
