"use client";

import { useEffect, useMemo, useState } from "react";
import { Bell, CheckCheck, ChevronDown } from "lucide-react";
import { alertKeys, buildInbox } from "@/lib/inbox";
import { day, dayTime, weekday } from "@/lib/format";
import type { AlertRules, Card, InboxData } from "@/lib/types";
import { validRules } from "../AlertRules";
import { publishUnreadAlerts } from "../shell/badge";
import { useStored } from "../useStored";
import FilingSheet, { type Opened } from "./FilingSheet";
import MiniChart from "./MiniChart";
import TickerChip from "./TickerChip";
import { dayMove, shorten, storyChart, storyFlag, storyHeadline } from "./story";
import u from "../ui.module.css";
import s from "./news.module.css";

export type ReadMap = Record<string, string>; // key -> when it was opened

export function useReadState() {
  return useStored<ReadMap>("finn.read.v1", {});
}

/** The user's alert rules (saved on this device), falling back to the pipeline's defaults. */
export function useAlertRules(data: InboxData): [AlertRules, (next: AlertRules) => void] {
  const [saved, setSaved] = useStored<AlertRules | null>("finn.rules.v1", null);
  const rules = useMemo(() => (saved ? validRules(saved, data.rules) : data.rules), [saved, data.rules]);
  return [rules, setSaved];
}

// The first screen enters once a visit: on the page load that opens FINN, not when you come
// back to News from another tab.
let entered = false;

export default function NewsFeed({ data }: { data: InboxData }) {
  const [entering] = useState(() => !entered);
  useEffect(() => {
    entered = true;
  }, []);
  const [windowKey, setWindowKey] = useStored<string>("finn.window", data.default_window);
  const [read, setRead, readLoaded] = useReadState();
  const [rules] = useAlertRules(data);
  const [cat, setCat] = useState("all");
  const [routineOpen, setRoutineOpen] = useState(false);
  const [open, setOpen] = useState<Opened>(null);

  const win = data.windows.find((w) => w.key === windowKey) ?? data.windows.find((w) => w.key === data.default_window)!;
  const view = useMemo(() => buildInbox(data, win.hours, rules), [data, win.hours, rules]);

  const all = [...view.needs, ...view.worth, ...view.routine];
  const cats = useMemo(() => {
    const m = new Map<string, { label: string; n: number }>();
    for (const c of [...view.needs, ...view.worth]) {
      const e = m.get(c.lead.category) ?? { label: c.lead.category_label, n: 0 };
      e.n += 1;
      m.set(c.lead.category, e);
    }
    return [...m.entries()].sort((a, b) => b[1].n - a[1].n);
  }, [view]);
  const activeCat = cat === "all" || cats.some(([k]) => k === cat) ? cat : "all";
  const pick = (cards: Card[]) => (activeCat === "all" ? cards : cards.filter((c) => c.lead.category === activeCat));
  const top = pick(view.needs);
  const latest = pick(view.worth).sort((a, b) => b.lead.datetime.localeCompare(a.lead.datetime));
  const routine = activeCat === "all" ? view.routine : [];
  const routineCount = routine.reduce((n, c) => n + c.members.length, 0);

  const isRead = (key: string) => key in read;
  const unread = [...top, ...latest].filter((c) => !isRead(c.key)).length;

  // The Alerts tab's badge: alerts in this window that haven't been opened.
  const alerts = useMemo(() => alertKeys(view), [view]);
  useEffect(() => {
    if (readLoaded) publishUnreadAlerts(alerts.filter((k) => !(k in read)).length);
  }, [alerts, read, readLoaded]);

  const openCard = (card: Card) => {
    setOpen({ type: "card", card });
    if (!isRead(card.key)) setRead((prev) => ({ ...prev, [card.key]: new Date().toISOString() }));
  };
  const markAllRead = () => {
    const now = new Date().toISOString();
    setRead((prev) => {
      const next = { ...prev };
      for (const c of all) next[c.key] ??= now;
      return next;
    });
  };

  const asOf = data.prices_as_of;
  return (
    <div className={u.page}>
      <header className={u.head}>
        <div className={`${u.titleRow}${entering ? " enter" : ""}`}>
          <h1 className={u.title}>News</h1>
        </div>
        <p className={`${u.sub}${entering ? " enter" : ""}`} style={entering ? { animationDelay: "60ms" } : undefined}>
          {readLoaded && (
            <>
              <strong>{unread}</strong> unread ·{" "}
            </>
          )}
          Filings {day(view.from)} – {day(view.to)}
          {asOf && ` · prices to ${weekday(asOf)} close`}
        </p>
        <div className={u.toolbar}>
          <div className={u.segment} role="group" aria-label="Time window">
            {data.windows.map((w) => (
              <button key={w.key} type="button" aria-pressed={w.key === win.key} onClick={() => setWindowKey(w.key)}>
                {w.label}
              </button>
            ))}
          </div>
          <button type="button" className={`${u.textButton} drawLine`} onClick={markAllRead} disabled={unread === 0}>
            <CheckCheck size={16} strokeWidth={2} aria-hidden="true" style={{ verticalAlign: "-3px", marginRight: 4 }} />
            Mark all read
          </button>
        </div>
        <div className={u.chips} role="group" aria-label="Filter by category">
          <button type="button" className={`${u.chip} press`} aria-pressed={activeCat === "all"} onClick={() => setCat("all")}>
            All <span className={u.chipCount}>{view.needs.length + view.worth.length}</span>
          </button>
          {cats.map(([key, c]) => (
            <button key={key} type="button" className={`${u.chip} press`} aria-pressed={activeCat === key} onClick={() => setCat(key)}>
              {c.label} <span className={u.chipCount}>{c.n}</span>
            </button>
          ))}
        </div>
      </header>

      {top.length > 0 && (
        <section className={u.section} aria-labelledby="top">
          <div className={u.sectionHead}>
            <h2 id="top">{data.tier_labels.needs_attention}</h2>
            <span>{top.length}</span>
          </div>
          <div className={s.stack}>
            {top.map((c, i) => (
              <Story key={c.key} card={c} data={data} big read={readLoaded && isRead(c.key)} onOpen={() => openCard(c)} index={i} enter={entering && i < 2} />
            ))}
          </div>
        </section>
      )}

      {latest.length > 0 && (
        <section className={u.section} aria-labelledby="latest">
          <div className={u.sectionHead}>
            <h2 id="latest">{data.tier_labels.worth_knowing}</h2>
            <span>{latest.length}</span>
          </div>
          <div className={s.list}>
            {latest.map((c, i) => (
              <Story key={c.key} card={c} data={data} read={readLoaded && isRead(c.key)} onOpen={() => openCard(c)} index={i} />
            ))}
          </div>
        </section>
      )}

      {top.length === 0 && latest.length === 0 && (
        <div className={u.empty}>
          <strong>No filings above routine</strong>
          {activeCat === "all" ? `Between ${day(view.from)} and ${day(view.to)}, only routine paperwork was filed.` : "None in this category in this window."}
          {activeCat === "all" && data.windows.some((w) => w.hours > win.hours) && (
            <div>
              <button
                type="button"
                className={u.textButton}
                onClick={() => setWindowKey(data.windows.find((w) => w.hours > win.hours)!.key)}
              >
                Look further back
              </button>
            </div>
          )}
        </div>
      )}

      {routine.length > 0 && (
        <section className={`${u.section} ${s.routine}`} data-open={routineOpen || undefined}>
          <button type="button" className={`${s.routineHead} row`} aria-expanded={routineOpen} onClick={() => setRoutineOpen((v) => !v)}>
            <span>
              <strong>{routineCount} routine filings</strong>
              <span className={s.routineSub}>ESOP allotments, compliance certificates, meeting notices</span>
            </span>
            <ChevronDown size={18} strokeWidth={2} aria-hidden="true" className={s.chev} />
          </button>
          {routineOpen && (
            <ul className={s.routineList}>
              {routine.map((c) => (
                <li key={c.key}>
                  <button type="button" className={`${s.routineRow} row`} onClick={() => openCard(c)}>
                    <span className={s.routineTitle}>{shorten(c.lead.headline)}</span>
                    <span className={s.meta}>
                      <span className="ticker">{c.lead.symbol}</span> · {c.lead.category_label} · {day(c.lead.datetime)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      <FilingSheet open={open} data={data} onClose={() => setOpen(null)} />
    </div>
  );
}

function Story({ card, data, big, read, onOpen, index, enter }: { card: Card; data: InboxData; big?: boolean; read: boolean; onOpen: () => void; index: number; enter?: boolean }) {
  const { lead } = card;
  const name = data.companies[lead.symbol]?.name ?? lead.symbol;
  const move = dayMove(data, lead.symbol);
  const flag = storyFlag(card);
  const chart = big ? storyChart(data, card) : null;
  return (
    <button type="button" className={`${big ? s.big : s.row} row${enter ? " enter" : ""}`}
      style={enter ? { animationDelay: `${180 + index * 60}ms` } : undefined}
      data-read={read || undefined}
      onClick={onOpen}
    >
      <span className={s.top}>
        <TickerChip symbol={lead.symbol} move={move.pct} date={move.date} />
        {flag && <span className={s.flag}>{flag}</span>}
        <span className={s.when}>
          {lead.category_label} · {dayTime(lead.datetime)}
        </span>
        {!read && <span className={s.unreadDot} aria-label="Unread" />}
      </span>
      <span className={s.headline}>{storyHeadline(card, data)}</span>
      <span className={s.meta}>
        {name}
        {card.members.length > 1 && ` · ${card.members.length} filings`}
        {card.alert && (
          <>
            {" · "}
            <Bell size={12} strokeWidth={2.25} aria-hidden="true" className={s.bell} />
            alert
          </>
        )}
      </span>
      {chart && (
        <span className={s.chart}>
          <MiniChart values={chart.values} mark={chart.mark} dates={chart.dates} filed={lead.datetime} />
        </span>
      )}
    </button>
  );
}
