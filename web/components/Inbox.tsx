"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Bell, ChevronDown, CircleCheck, ExternalLink, Moon, SlidersHorizontal, Sun, X } from "lucide-react";
import { alertKeys, buildInbox } from "@/lib/inbox";
import { day, plural } from "@/lib/format";
import type { AlertRules, Card, InboxData, PriceAlert } from "@/lib/types";
import AlertRulesPanel, { validRules } from "./AlertRules";
import { FilingCard, PriceCard } from "./Cards";
import { FilingDetail, PriceDetail } from "./Details";
import Sheet from "./Sheet";
import { useStored } from "./useStored";
import s from "./inbox.module.css";
import rs from "./rules.module.css";
import sh from "./sheet.module.css";

type Done = Record<string, string>; // key -> when it was cleared
type Open = { type: "price"; alert: PriceAlert } | { type: "card"; card: Card } | null;

export default function Inbox({ data }: { data: InboxData }) {
  const [windowKey, setWindowKey] = useStored<string>("finn.window", data.default_window);
  const [done, setDone] = useStored<Done>("finn.done.v1", {});
  const [hintGone, setHintGone, hintLoaded] = useStored<boolean>("finn.hint.v1", false);
  const [alertsOnly, setAlertsOnly] = useState(false);
  const [pricesOpen, setPricesOpen] = useState(false);
  const [routineOpen, setRoutineOpen] = useState(false);
  const [clearedOpen, setClearedOpen] = useState(false);
  const [open, setOpen] = useState<Open>(null);
  const [toast, setToast] = useState<{ key: string; label: string } | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [savedRules, setRules] = useStored<AlertRules | null>("finn.rules.v1", null);
  const [rulesOpen, setRulesOpen] = useState(false);
  const rules = useMemo(() => (savedRules ? validRules(savedRules, data.rules) : data.rules), [savedRules, data.rules]);
  const customRules = savedRules !== null && JSON.stringify(rules) !== JSON.stringify(data.rules);

  const win = data.windows.find((w) => w.key === windowKey) ?? data.windows.find((w) => w.key === data.default_window)!;
  const view = useMemo(() => buildInbox(data, win.hours, rules), [data, win.hours, rules]);
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
  const openAlerts = [...alerts].filter((k) => !isDone(k)).length; // the bell badge and the hero pill
  const routineFilings = view.routine.reduce((n, c) => n + c.members.length, 0);
  const wider = data.windows.find((w) => w.hours > win.hours);
  const showHint = hintLoaded && !hintGone && left > 0;

  const mark = useCallback(
    (key: string, label: string) => {
      setDone((prev) => ({ ...prev, [key]: new Date().toISOString() }));
      setHintGone(true);
      setToast({ key, label });
      if (toastTimer.current) clearTimeout(toastTimer.current);
      toastTimer.current = setTimeout(() => setToast(null), 4500);
    },
    [setDone, setHintGone],
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

  const toggleAlerts = () =>
    setAlertsOnly((v) => {
      if (!v) setPricesOpen(true);
      return !v;
    });

  const openSheet = (o: Open) => {
    setOpen(o);
    setHintGone(true);
  };
  const close = useCallback(() => setOpen(null), []);
  const closeRules = useCallback(() => setRulesOpen(false), []);
  const openKey = open ? (open.type === "price" ? open.alert.key : open.card.key) : null;

  return (
    <div className={s.app}>
      <header className={s.top}>
        <div className={s.brand}>
          <svg width="26" height="26" viewBox="0 0 64 64" aria-hidden="true">
            <rect width="64" height="64" rx="16" fill="var(--card)" stroke="var(--border)" strokeWidth="2" />
            <path d="M22 46V18h21M22 32h16" fill="none" stroke="var(--fg)" strokeWidth="6" />
            <rect x="40" y="40" width="6" height="6" rx="1" fill="var(--teal)" />
          </svg>
          <span>Finn</span>
        </div>
        <div className={s.actions}>
          <ThemeToggle />
          <button
            type="button"
            className={s.iconButton}
            aria-label={customRules ? "Alert rules (your own)" : "Alert rules"}
            aria-haspopup="dialog"
            onClick={() => setRulesOpen(true)}
          >
            <SlidersHorizontal size={20} strokeWidth={1.75} />
            {customRules && <span className={rs.dot} aria-hidden="true" />}
          </button>
          <button
            type="button"
            className={s.iconButton}
            aria-pressed={alertsOnly}
            aria-label={`${alertsOnly ? "Show everything" : "Show alerts only"}: ${plural(openAlerts, "open alert")}`}
            onClick={toggleAlerts}
          >
            <Bell size={20} strokeWidth={1.75} />
            {openAlerts > 0 && <span className={s.badge}>{openAlerts}</span>}
          </button>
        </div>
      </header>

      <section className={s.hero} aria-live="polite">
        <h1 className={s.count}>
          <span className={s.countValue}>{left}</span>
          <span className={s.countLabel}>{alertsOnly ? (left === 1 ? "alert to review" : "alerts to review") : left === 1 ? "item to review" : "items to review"}</span>
        </h1>
        <p className={s.heroSub}>
          {openAlerts > 0 && (
            <button type="button" className={s.alertPill} onClick={toggleAlerts} aria-pressed={alertsOnly}>
              <Bell size={12} strokeWidth={2.25} aria-hidden="true" />
              {plural(openAlerts, "alert")}
            </button>
          )}
          <span>
            {cleared.length} of {total} cleared
          </span>
        </p>
        <div className={s.progress} role="progressbar" aria-label="Cleared" aria-valuemin={0} aria-valuemax={total} aria-valuenow={cleared.length}>
          <span style={{ transform: `scaleX(${total ? cleared.length / total : 0})` }} />
        </div>
        <div className={s.segment} role="group" aria-label="Time window">
          {data.windows.map((w) => (
            <button key={w.key} type="button" aria-pressed={w.key === win.key} onClick={() => setWindowKey(w.key)}>
              {w.label}
            </button>
          ))}
        </div>
        <p className={s.range}>
          {day(view.from)} – {day(view.to)}
          {data.prices_as_of && <> · prices to {day(data.prices_as_of)} close</>}
        </p>
      </section>

      <main className={s.main}>
        {showHint && (
          <div className={s.hint}>
            <span>Swipe a card left to clear it. Tap for details.</span>
            <button type="button" aria-label="Dismiss tip" onClick={() => setHintGone(true)}>
              <X size={16} strokeWidth={2} />
            </button>
          </div>
        )}

        {alertsOnly && (
          <div className={s.filterBar}>
            <span>Showing alerts only</span>
            <button type="button" onClick={() => setAlertsOnly(false)}>
              Show all
            </button>
          </div>
        )}

        {left === 0 && (
          <AllClear
            empty={total === 0}
            note={data.schedule_note}
            wider={wider ? { label: wider.label, onClick: () => setWindowKey(wider.key) } : null}
          />
        )}

        {openNeeds.length > 0 && (
          <Section title={data.tier_labels.needs_attention} count={openNeeds.length}>
            {openNeeds.map((c) => (
              <FilingCard key={c.key} card={c} data={data} onOpen={() => openSheet({ type: "card", card: c })} onDone={() => mark(c.key, c.lead.symbol)} />
            ))}
          </Section>
        )}

        {openWorth.length > 0 && (
          <Section title={data.tier_labels.worth_knowing} count={openWorth.length}>
            {openWorth.map((c) => (
              <FilingCard key={c.key} card={c} data={data} onOpen={() => openSheet({ type: "card", card: c })} onDone={() => mark(c.key, c.lead.symbol)} />
            ))}
          </Section>
        )}

        {openPrice.length > 0 && (
          <Accordion title="Price alerts" count={openPrice.length} open={pricesOpen} onToggle={() => setPricesOpen((v) => !v)}>
            <div className={s.stack}>
              {openPrice.map((a) => (
                <PriceCard key={a.key} alert={a} data={data} onOpen={() => openSheet({ type: "price", alert: a })} onDone={() => mark(a.key, a.name)} />
              ))}
            </div>
          </Accordion>
        )}

        {!alertsOnly && view.routine.length > 0 && (
          <Accordion
            title={`${data.tier_labels.routine} filings`}
            count={routineFilings}
            sub="Not counted in your queue"
            open={routineOpen}
            onToggle={() => setRoutineOpen((v) => !v)}
          >
            <ul className={s.list}>
              {view.routine.map((c) => (
                <li key={c.key}>
                  <button type="button" className={s.listRow} onClick={() => openSheet({ type: "card", card: c })}>
                    <span className={s.listTitle}>{c.lead.headline}</span>
                    <span className={s.listMeta}>
                      <span className="ticker">{c.lead.symbol}</span>
                      <span className="sep" aria-hidden="true">·</span>
                      {c.lead.category_label}
                      <span className="sep" aria-hidden="true">·</span>
                      {day(c.lead.datetime)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </Accordion>
        )}

        {cleared.length > 0 && (
          <Accordion title="Cleared" count={cleared.length} open={clearedOpen} onToggle={() => setClearedOpen((v) => !v)}>
            <ul className={s.list}>
              {cleared.map((r) => (
                <li key={r.key} className={s.clearedRow}>
                  <span className={s.clearedText}>
                    <span className="ticker">{r.symbol}</span> {r.text}
                  </span>
                  <button type="button" className={s.undo} onClick={() => unmark(r.key)}>
                    Undo
                  </button>
                </li>
              ))}
            </ul>
          </Accordion>
        )}

        <footer className={s.footer}>
          Filings from BSE · prices from Yahoo Finance, end of day · results checked against screener.in. Rankings
          tell you what to read first; they aren&apos;t advice.
        </footer>
      </main>

      <Sheet open={rulesOpen} label="Alert rules" onClose={closeRules}>
        <AlertRulesPanel
          rules={rules}
          defaults={data.rules}
          choices={data.alert_choices}
          alertCount={alerts.size}
          windowLabel={win.label}
          needsAt={data.tiers.needs_attention}
          onChange={(next) => setRules(next)}
        />
      </Sheet>

      <Sheet
        open={open !== null}
        label={open?.type === "price" ? `${open.alert.name} price alert` : open ? data.companies[open.card.lead.symbol]?.name ?? open.card.lead.symbol : ""}
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
                  {isDone(openKey) ? "Move back to inbox" : "Mark as done"}
                </button>
              )}
            </>
          )
        }
      >
        {open?.type === "price" && <PriceDetail key={open.alert.key} alert={open.alert} data={data} />}
        {open?.type === "card" && <FilingDetail key={open.card.key} card={open.card} data={data} />}
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
        {title}
        <span className={s.pill}>{count}</span>
      </h2>
      <div className={s.stack}>{children}</div>
    </section>
  );
}

function Accordion({
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
    <section className={s.accordion} data-open={open || undefined}>
      <button type="button" className={s.accordionHead} aria-expanded={open} onClick={onToggle}>
        <span className={s.accordionText}>
          <span className={s.accordionTitle}>
            {title}
            <span className={s.pill}>{count}</span>
          </span>
          {sub && <span className={s.accordionSub}>{sub}</span>}
        </span>
        <ChevronDown size={18} strokeWidth={2} className={s.chev} aria-hidden="true" />
      </button>
      <div className={s.accordionBody} aria-hidden={!open}>
        <div className={s.accordionInner}>{open && children}</div>
      </div>
    </section>
  );
}

function AllClear({ empty, note, wider }: { empty: boolean; note: string; wider: { label: string; onClick: () => void } | null }) {
  return (
    <section className={s.clear}>
      <CircleCheck size={32} strokeWidth={1.5} aria-hidden="true" className={s.clearIcon} />
      <h2>{empty ? "Nothing new in this window" : "All clear"}</h2>
      <p>
        {empty ? "No alerts or filings worth reading." : "You've been through everything worth reading."} {note}
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
        document.querySelector('meta[name="theme-color"]')?.setAttribute("content", next === "light" ? "#f5f3ee" : "#0b0e14");
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
