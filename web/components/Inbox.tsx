"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Bell, ChevronRight, CircleCheck, ExternalLink, Moon, Sun } from "lucide-react";
import { alertKeys, buildInbox } from "@/lib/inbox";
import { day, dayTime, direction, pct, plural } from "@/lib/format";
import { alertReason, keyFigure, sparkValues } from "@/lib/present";
import type { Card, InboxData, PriceAlert } from "@/lib/types";
import { FilingDetail, Move, PriceDetail } from "./Details";
import Sheet from "./Sheet";
import Spark from "./Spark";
import SwipeRow from "./SwipeRow";
import { useStored } from "./useStored";
import s from "./inbox.module.css";
import sh from "./sheet.module.css";

type Done = Record<string, string>; // key -> when it was cleared
type Open = { type: "price"; alert: PriceAlert } | { type: "card"; card: Card } | null;

export default function Inbox({ data }: { data: InboxData }) {
  const [windowKey, setWindowKey] = useStored<string>("finn.window", data.default_window);
  const [done, setDone] = useStored<Done>("finn.done.v1", {});
  const [alertsOnly, setAlertsOnly] = useState(false);
  const [routineOpen, setRoutineOpen] = useState(false);
  const [clearedOpen, setClearedOpen] = useState(false);
  const [open, setOpen] = useState<Open>(null);
  const [toast, setToast] = useState<{ key: string; label: string } | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const win = data.windows.find((w) => w.key === windowKey) ?? data.windows.find((w) => w.key === data.default_window)!;
  const view = useMemo(() => buildInbox(data, win.hours), [data, win.hours]);
  const alerts = useMemo(() => new Set(alertKeys(view)), [view]);

  const isDone = (key: string) => key in done;
  const pick = (cards: Card[]) => cards.filter((c) => !alertsOnly || c.alert);
  const needs = pick(view.needs);
  const worth = pick(view.worth);
  const openPrice = view.priceAlerts.filter((a) => !isDone(a.key));
  const openNeeds = needs.filter((c) => !isDone(c.key));
  const openWorth = worth.filter((c) => !isDone(c.key));
  const cleared = [
    ...view.priceAlerts.filter((a) => isDone(a.key)).map((a) => ({ key: a.key, symbol: a.symbol, text: a.name })),
    ...[...needs, ...worth].filter((c) => isDone(c.key)).map((c) => ({ key: c.key, symbol: c.lead.symbol, text: c.lead.headline })),
  ];
  const left = openPrice.length + openNeeds.length + openWorth.length;
  const total = left + cleared.length;
  const badge = [...alerts].filter((k) => !isDone(k)).length;
  const routineFilings = view.routine.reduce((n, c) => n + c.members.length, 0);
  const wider = data.windows.find((w) => w.hours > win.hours);

  const mark = useCallback(
    (key: string, label: string) => {
      setDone((prev) => ({ ...prev, [key]: new Date().toISOString() }));
      setToast({ key, label });
      if (toastTimer.current) clearTimeout(toastTimer.current);
      toastTimer.current = setTimeout(() => setToast(null), 4500);
    },
    [setDone],
  );

  const unmark = useCallback(
    (key: string) => {
      setDone((prev) => {
        const next = { ...prev };
        delete next[key];
        return next;
      });
      setToast((t) => (t?.key === key ? null : t));
    },
    [setDone],
  );

  useEffect(
    () => () => {
      if (toastTimer.current) clearTimeout(toastTimer.current);
    },
    [],
  );

  const close = useCallback(() => setOpen(null), []);
  const openKey = open ? (open.type === "price" ? open.alert.key : open.card.key) : null;

  return (
    <div className={s.app}>
      <header className={s.top}>
        <div className={s.brand}>
          <svg width="22" height="22" viewBox="0 0 64 64" aria-hidden="true">
            <rect width="64" height="64" rx="14" fill="var(--fg)" />
            <path d="M22 46V18h21M22 32h16" fill="none" stroke="var(--bg)" strokeWidth="6" />
          </svg>
          <span>Finn</span>
        </div>
        <div className={s.actions}>
          <ThemeToggle />
          <button
            type="button"
            className={s.iconButton}
            aria-pressed={alertsOnly}
            aria-label={`${alertsOnly ? "Show everything" : "Show alerts only"}, ${plural(badge, "open alert")}`}
            onClick={() => setAlertsOnly((v) => !v)}
          >
            <Bell size={20} strokeWidth={1.75} />
            {badge > 0 && <span className={`num ${s.badge}`}>{badge}</span>}
          </button>
        </div>
      </header>

      <section className={s.queue} aria-live="polite">
        <h1 className={s.count}>
          <span className="num">{left}</span> {alertsOnly ? (left === 1 ? "alert" : "alerts") : "left"}
        </h1>
        <p className={s.queueSub}>
          <span className="num">{cleared.length}</span> of <span className="num">{total}</span> cleared<span className="sep" aria-hidden="true">·</span>
          {day(view.from)} – {day(view.to)}
        </p>
        <div className={s.line} role="progressbar" aria-label="Cleared" aria-valuemin={0} aria-valuemax={total} aria-valuenow={cleared.length}>
          <span style={{ transform: `scaleX(${total ? cleared.length / total : 0})` }} />
        </div>
        <div className={s.tabs} role="group" aria-label="Time window">
          {data.windows.map((w) => (
            <button key={w.key} type="button" className={s.tab} aria-pressed={w.key === win.key} onClick={() => setWindowKey(w.key)}>
              <span className="num">{w.label}</span>
            </button>
          ))}
          {alertsOnly && (
            <button type="button" className={s.filterOff} onClick={() => setAlertsOnly(false)}>
              Alerts only · show all
            </button>
          )}
        </div>
      </section>

      <main className={s.main}>
        {left === 0 ? (
          <AllClear
            empty={total === 0}
            from={view.from}
            to={view.to}
            note={data.schedule_note}
            wider={wider ? { label: wider.label, onClick: () => setWindowKey(wider.key) } : null}
          />
        ) : (
          cleared.length === 0 && <p className={s.hint}>Swipe left to clear. Tap for details.</p>
        )}

        {openPrice.length > 0 && (
          <Section title="Price alerts" count={openPrice.length}>
            {openPrice.map((a) => (
              <PriceRow
                key={a.key}
                alert={a}
                data={data}
                onOpen={() => setOpen({ type: "price", alert: a })}
                onDone={() => mark(a.key, a.name)}
              />
            ))}
          </Section>
        )}
        {openNeeds.length > 0 && (
          <Section title={data.tier_labels.needs_attention} count={openNeeds.length}>
            {openNeeds.map((c) => (
              <CardRow key={c.key} card={c} data={data} onOpen={() => setOpen({ type: "card", card: c })} onDone={() => mark(c.key, c.lead.symbol)} />
            ))}
          </Section>
        )}
        {openWorth.length > 0 && (
          <Section title={data.tier_labels.worth_knowing} count={openWorth.length}>
            {openWorth.map((c) => (
              <CardRow key={c.key} card={c} data={data} onOpen={() => setOpen({ type: "card", card: c })} onDone={() => mark(c.key, c.lead.symbol)} />
            ))}
          </Section>
        )}

        {!alertsOnly && view.routine.length > 0 && (
          <Fold
            title={`${data.tier_labels.routine} filings`}
            count={routineFilings}
            sub={`${routineMix(view.routine)}. Not counted.`}
            open={routineOpen}
            onToggle={() => setRoutineOpen((v) => !v)}
          >
            {view.routine.map((c) => (
              <li key={c.key}>
                <button type="button" className={s.mini} onClick={() => setOpen({ type: "card", card: c })}>
                  <span className={s.miniTitle}>{c.lead.headline}</span>
                  <span className={s.meta}>
                    <span className="num">{c.lead.symbol}</span><span className="sep" aria-hidden="true">·</span>{c.lead.category_label}<span className="sep" aria-hidden="true">·</span>{day(c.lead.datetime)}
                  </span>
                </button>
              </li>
            ))}
          </Fold>
        )}

        {cleared.length > 0 && (
          <Fold title="Cleared" count={cleared.length} open={clearedOpen} onToggle={() => setClearedOpen((v) => !v)}>
            {cleared.map((r) => (
              <li key={r.key} className={s.clearedItem}>
                <span className={s.clearedText}>
                  <span className="num">{r.symbol}</span> {r.text}
                </span>
                <button type="button" className={s.textButton} onClick={() => unmark(r.key)}>
                  Undo
                </button>
              </li>
            ))}
          </Fold>
        )}

        <footer className={s.footer}>
          Filings from BSE · prices from Yahoo Finance, end of day · results checked against screener.in. Rankings
          tell you what to read first; they aren&apos;t advice.
        </footer>
      </main>

      <Sheet
        open={open !== null}
        label={open?.type === "price" ? `${open.alert.name} price alert` : open?.card.lead.headline ?? ""}
        onClose={close}
        footer={
          open && (
            <>
              {open.type === "card" && open.card.lead.pdf_url ? (
                <a className={sh.link} href={open.card.lead.pdf_url} target="_blank" rel="noopener noreferrer">
                  Open filing <ExternalLink size={15} strokeWidth={1.75} aria-hidden="true" />
                </a>
              ) : (
                <span />
              )}
              {openKey && !(open.type === "card" && open.card.lead.tier === "routine") && (
                <button
                  type="button"
                  className={sh.primary}
                  onClick={() => {
                    if (isDone(openKey)) unmark(openKey);
                    else mark(openKey, open.type === "price" ? open.alert.name : open.card.lead.symbol);
                    close();
                  }}
                >
                  {isDone(openKey) ? "Move back to inbox" : "Done"}
                </button>
              )}
            </>
          )
        }
      >
        {open?.type === "price" && <PriceDetail alert={open.alert} data={data} />}
        {open?.type === "card" && <FilingDetail card={open.card} data={data} />}
      </Sheet>

      {toast && (
        <div className={s.toast} role="status">
          <span className={s.toastText}>Cleared {toast.label}</span>
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
        <span className="num">{count}</span>
      </h2>
      <div className={s.rows}>{children}</div>
    </section>
  );
}

function PriceRow({ alert, data, onOpen, onDone }: { alert: PriceAlert; data: InboxData; onOpen: () => void; onDone: () => void }) {
  const series = data.prices[alert.symbol];
  const dir = direction(alert.pct_change);
  return (
    <SwipeRow label={`${alert.name}, ${pct(alert.pct_change)}. Open details`} onOpen={onOpen} onDone={onDone}>
      <div className={s.rowMain}>
        <span className={s.title}>{alert.name}</span>
        <span className={s.meta}>
          <span className="num">{alert.symbol}</span><span className="sep" aria-hidden="true">·</span>{day(alert.date)}<span className="sep" aria-hidden="true">·</span>
          {alertReason(alert, data.rules, series?.volume_avg_window ?? 20)}
        </span>
      </div>
      <div className={s.key}>
        <Spark values={sparkValues(series, alert.date, data.spark_sessions)} dir={dir} />
        <Move value={alert.pct_change} className={s.keyValue} />
      </div>
    </SwipeRow>
  );
}

function CardRow({ card, data, onOpen, onDone }: { card: Card; data: InboxData; onOpen: () => void; onDone: () => void }) {
  const { lead } = card;
  const fig = keyFigure(card, data, day);
  return (
    <SwipeRow label={`${lead.symbol}: ${lead.headline}. Open details`} onOpen={onOpen} onDone={onDone}>
      <div className={s.rowMain}>
        <span className={s.title}>{lead.headline}</span>
        <span className={s.meta}>
          {card.alert && <Bell size={12} strokeWidth={2} aria-label="Alert" className={s.metaIcon} />}
          <span className="num">{lead.symbol}</span><span className="sep" aria-hidden="true">·</span>{lead.category_label}<span className="sep" aria-hidden="true">·</span>{day(lead.datetime)}
        </span>
      </div>
      {fig && (
        <div className={s.key}>
          {fig.kind === "flag" ? (
            <span className={s.flag}>{fig.label}</span>
          ) : (
            <>
              {fig.kind === "move" ? (
                <Move value={fig.value} className={s.keyValue} />
              ) : (
                <span className={`num ${s.keyValue}`}>{pct(fig.value, 1)}</span>
              )}
              <span className={s.keyCaption}>{fig.caption}</span>
            </>
          )}
        </div>
      )}
    </SwipeRow>
  );
}

function Fold({
  title,
  count,
  sub,
  open,
  onToggle,
  children,
}: {
  title: string;
  count: number;
  sub?: string;
  open: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <section className={s.fold}>
      <button type="button" className={s.foldHead} aria-expanded={open} onClick={onToggle}>
        <span className={s.foldText}>
          <span className={s.foldTitle}>
            {title} <span className={`num ${s.foldCount}`}>{count}</span>
          </span>
          {sub && <span className={s.meta}>{sub}</span>}
        </span>
        <ChevronRight size={18} strokeWidth={1.75} className={s.chev} aria-hidden="true" />
      </button>
      {open && <ul className={s.foldList}>{children}</ul>}
    </section>
  );
}

function AllClear({
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
    <section className={s.clear}>
      <CircleCheck size={28} strokeWidth={1.5} aria-hidden="true" />
      <h2>{empty ? "Nothing new here" : "All clear"}</h2>
      <p>
        {empty ? "No alerts or filings worth reading" : "You've been through everything"} from{" "}
        <span className="num">{dayTime(from)}</span> to <span className="num">{dayTime(to)}</span>. {note}
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
  const [theme, setTheme] = useState<"light" | "dark">("dark");
  useEffect(() => {
    setTheme(document.documentElement.dataset.theme === "light" ? "light" : "dark");
  }, []);
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button
      type="button"
      className={s.iconButton}
      aria-label={`Switch to ${next} mode`}
      onClick={() => {
        document.documentElement.dataset.theme = next;
        document.querySelector('meta[name="theme-color"]')?.setAttribute("content", next === "light" ? "#f6f1e6" : "#0e1013");
        try {
          localStorage.setItem("finn.theme", next); // raw string: read by the pre-paint script in layout.tsx
        } catch {
          /* storage unavailable */
        }
        setTheme(next);
      }}
    >
      {theme === "dark" ? <Sun size={20} strokeWidth={1.75} /> : <Moon size={20} strokeWidth={1.75} />}
    </button>
  );
}

function routineMix(cards: Card[]): string {
  const counts = new Map<string, number>();
  let other = 0;
  for (const c of cards) {
    if (c.lead.category === "unclassified") other += c.members.length;
    else counts.set(c.lead.category_label, (counts.get(c.lead.category_label) ?? 0) + c.members.length);
  }
  const top = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 3).map(([label]) => label);
  const text = top.join(", ") + (other || counts.size > 3 ? " and other paperwork" : "");
  return text.replace(/^./, (c) => c.toUpperCase());
}
