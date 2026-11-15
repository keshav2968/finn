"use client";

import { useEffect, useMemo, useState } from "react";
import { BellRing, CheckCheck, Download, Smartphone } from "lucide-react";
import { alertKeys, buildInbox } from "@/lib/inbox";
import { day, dayTime, pct, times } from "@/lib/format";
import { alertReasons } from "@/lib/present";
import type { Card, InboxData, PriceAlert } from "@/lib/types";
import AlertRulesPanel from "../AlertRules";
import FilingSheet, { type Opened } from "../news/FilingSheet";
import TickerChip from "../news/TickerChip";
import { useAlertRules, useReadState } from "../news/NewsFeed";
import { dayMove, storyHeadline } from "../news/story";
import { publishUnreadAlerts } from "../shell/badge";
import { IosSteps } from "../shell/InstallPrompt";
import { useInstall } from "../shell/install";
import { useStored } from "../useStored";
import u from "../ui.module.css";
import s from "./alerts.module.css";

type Row = { kind: "price"; key: string; at: string; alert: PriceAlert } | { kind: "filing"; key: string; at: string; card: Card };

export default function AlertsView({ data }: { data: InboxData }) {
  const [windowKey, setWindowKey] = useStored<string>("finn.window", data.default_window);
  const [rules, setRules] = useAlertRules(data);
  const [read, setRead, readLoaded] = useReadState();
  const [open, setOpen] = useState<Opened>(null);

  const win = data.windows.find((w) => w.key === windowKey) ?? data.windows.find((w) => w.key === data.default_window)!;
  const view = useMemo(() => buildInbox(data, win.hours, rules), [data, win.hours, rules]);
  const keys = useMemo(() => alertKeys(view), [view]);

  const rows: Row[] = useMemo(() => {
    const out: Row[] = view.priceAlerts.map((a) => ({ kind: "price" as const, key: a.key, at: `${a.date}T15:30:00+05:30`, alert: a }));
    for (const c of [...view.needs, ...view.worth, ...view.routine]) if (c.alert) out.push({ kind: "filing", key: c.key, at: c.lead.datetime, card: c });
    return out.sort((a, b) => Date.parse(b.at) - Date.parse(a.at));
  }, [view]);

  const unread = rows.filter((r) => !(r.key in read)).length;
  useEffect(() => {
    if (readLoaded) publishUnreadAlerts(keys.filter((k) => !(k in read)).length);
  }, [keys, read, readLoaded]);

  const openRow = (r: Row) => {
    setOpen(r.kind === "price" ? { type: "price", alert: r.alert } : { type: "card", card: r.card });
    if (!(r.key in read)) setRead((prev) => ({ ...prev, [r.key]: new Date().toISOString() }));
  };
  const markAll = () => {
    const now = new Date().toISOString();
    setRead((prev) => {
      const next = { ...prev };
      for (const r of rows) next[r.key] ??= now;
      return next;
    });
  };

  return (
    <div className={u.page}>
      <header className={u.head}>
        <div className={u.titleRow}>
          <h1 className={u.title}>Alerts</h1>
        </div>
        <p className={u.sub}>Price moves and filings that crossed your rules. The rules are saved on this phone.</p>
      </header>

      <section className={u.section} aria-labelledby="caught">
        <div className={s.row}>
          <div className={u.sectionHead}>
            <h2 id="caught">Alerts in the last {win.label}</h2>
            <span>{readLoaded ? `${unread} unread` : ""}</span>
          </div>
          <button type="button" className={`${u.textButton} drawLine`} onClick={markAll} disabled={unread === 0}>
            <CheckCheck size={16} strokeWidth={2} aria-hidden="true" style={{ verticalAlign: "-3px", marginRight: 4 }} />
            Mark all read
          </button>
        </div>
        <div className={u.segment} role="group" aria-label="Time window">
          {data.windows.map((w) => (
            <button key={w.key} type="button" aria-pressed={w.key === win.key} onClick={() => setWindowKey(w.key)}>
              {w.label}
            </button>
          ))}
        </div>
        {rows.length === 0 ? (
          <div className={u.empty}>
            <strong>Nothing crossed your rules</strong>
            Between {day(view.from)} and {day(view.to)}. Loosen a rule below or look further back.
          </div>
        ) : (
          <ul className={s.list}>
            {rows.map((r, i) => {
              const isRead = readLoaded && r.key in read;
              const symbol = r.kind === "price" ? r.alert.symbol : r.card.lead.symbol;
              const move = r.kind === "price" ? { pct: r.alert.pct_change, date: r.alert.date } : dayMove(data, symbol);
              return (
                <li key={r.key}>
                  <button type="button" className={`${s.item} row`} data-read={isRead || undefined} onClick={() => openRow(r)}>
                    <span className={s.icon} data-kind={r.kind} aria-hidden="true">
                      <BellRing size={16} strokeWidth={2} />
                    </span>
                    <span className={s.body}>
                      <span className={s.top}>
                        <TickerChip symbol={symbol} move={move.pct} date={move.date} />
                        <span className={s.when}>{r.kind === "price" ? `${day(r.alert.date)} close` : dayTime(r.card.lead.datetime)}</span>
                      </span>
                      <span className={s.title}>
                        {r.kind === "price" ? alertReasons(r.alert, data.prices[symbol]?.volume_avg_window ?? 20).join(" · ") : storyHeadline(r.card, data)}
                      </span>
                      <span className={s.meta}>
                        {r.kind === "price"
                          ? `${r.alert.name} · price ${pct(r.alert.pct_change, 1)}${r.alert.vol_ratio !== null ? ` · volume ${times(r.alert.vol_ratio)}` : ""}`
                          : `${data.companies[symbol]?.name ?? symbol} · ${r.card.lead.category_label}`}
                      </span>
                    </span>
                    {!isRead && <span className={s.dot} aria-label="Unread" />}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section className={`${u.section} ${s.panel}`} aria-label="Alert rules">
        <AlertRulesPanel
          rules={rules}
          defaults={data.rules}
          choices={data.alert_choices}
          alertCount={keys.length}
          windowLabel={win.label}
          needsAt={data.tiers.needs_attention}
          onChange={(next) => setRules(next)}
        />
      </section>

      <section className={u.section} aria-labelledby="look">
        <h2 id="look" className={u.sectionHead}>
          Appearance
        </h2>
        <ThemeChoice />
      </section>

      <section className={u.section} aria-labelledby="install">
        <h2 id="install" className={u.sectionHead}>
          Install FINN
        </h2>
        <InstallCard />
      </section>

      <section className={u.section} aria-labelledby="push">
        <h2 id="push" className={u.sectionHead}>
          Phone notifications
        </h2>
        <p className={s.plain}>
          Off. FINN lists alerts here when you open it and sends nothing to your phone. The data is the 14 Nov snapshot,
          so there is nothing new to send until the daily refresh runs again.
        </p>
      </section>

      <FilingSheet open={open} data={data} onClose={() => setOpen(null)} />
    </div>
  );
}

function ThemeChoice() {
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  useEffect(() => setTheme(document.documentElement.dataset.theme === "light" ? "light" : "dark"), []);
  const choose = (t: "dark" | "light") => {
    document.documentElement.dataset.theme = t;
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", t === "light" ? "#f5f3ee" : "#0b0e14");
    try {
      localStorage.setItem("finn.theme", t); // raw string: read by the pre-paint script in layout.tsx
    } catch {
      /* storage blocked */
    }
    setTheme(t);
  };
  return (
    <div className={u.segment} role="group" aria-label="Theme">
      {(["dark", "light"] as const).map((t) => (
        <button key={t} type="button" aria-pressed={theme === t} onClick={() => choose(t)} style={{ fontFamily: "var(--font-text)" }}>
          {t === "dark" ? "Dark" : "Light"}
        </button>
      ))}
    </div>
  );
}

function InstallCard() {
  const { ready, standalone, ios, canPrompt, state, prompt } = useInstall();
  if (!ready) return <span className="skel" style={{ height: 72 }} aria-hidden="true" />;
  if (standalone || state === "installed") {
    return (
      <div className={s.card}>
        <Smartphone size={20} strokeWidth={1.75} aria-hidden="true" />
        <p>{standalone ? "You're using the installed app." : "FINN is installed on this device. Open it from your home screen."}</p>
      </div>
    );
  }
  if (ios) {
    return (
      <div className={s.card} data-stack>
        <IosSteps />
      </div>
    );
  }
  if (canPrompt) {
    return (
      <div className={s.card}>
        <Download size={20} strokeWidth={1.75} aria-hidden="true" />
        <p>Add FINN to your home screen: it opens full screen, like any app.</p>
        <button type="button" className={`${s.go} press`} onClick={() => void prompt()}>
          Install
        </button>
      </div>
    );
  }
  return (
    <div className={s.card}>
      <Smartphone size={20} strokeWidth={1.75} aria-hidden="true" />
      <p>
        Open FINN in Chrome on Android or Safari on iPhone to install it. On a desktop, Chrome and Edge show an install icon in
        the address bar.
      </p>
    </div>
  );
}
