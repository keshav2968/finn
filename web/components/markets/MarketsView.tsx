"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Check, Pencil } from "lucide-react";
import { direction, pct, rupees, times, weekday } from "@/lib/format";
import type { Quote } from "@/lib/data";
import Delta from "../Delta";
import Sheet from "../Sheet";
import Spark from "../Spark";
import { CountUp } from "../motion";
import { useStored } from "../useStored";
import sh from "../sheet.module.css";
import u from "../ui.module.css";
import s from "./markets.module.css";

type Movers = "gainers" | "losers" | "volume";

export default function MarketsView({ quotes }: { quotes: Quote[] }) {
  const all = quotes.map((q) => q.symbol);
  const [watch, setWatch, loaded] = useStored<string[]>("finn.watch.v1", all);
  const [movers, setMovers] = useState<Movers>("gainers");
  const [editing, setEditing] = useState(false);

  const asOf = quotes[0]?.as_of;
  const listed = quotes.filter((q) => watch.includes(q.symbol));
  const up = quotes.filter((q) => (q.pct_change ?? 0) > 0).length;
  const down = quotes.filter((q) => (q.pct_change ?? 0) < 0).length;

  const moverList = useMemo(() => {
    const by = [...quotes];
    if (movers === "gainers") return by.filter((q) => (q.pct_change ?? 0) > 0).sort((a, b) => (b.pct_change ?? 0) - (a.pct_change ?? 0)).slice(0, 5);
    if (movers === "losers") return by.filter((q) => (q.pct_change ?? 0) < 0).sort((a, b) => (a.pct_change ?? 0) - (b.pct_change ?? 0)).slice(0, 5);
    return by.filter((q) => q.vol_ratio !== null).sort((a, b) => (b.vol_ratio ?? 0) - (a.vol_ratio ?? 0)).slice(0, 5);
  }, [quotes, movers]);

  return (
    <div className={u.page}>
      <header className={u.head}>
        <div className={u.titleRow}>
          <h1 className={u.title}>Markets</h1>
          <span className={u.status}>
            <span className={u.statusDot} aria-hidden="true" />
            {asOf ? `Close · ${weekday(asOf)}` : "Snapshot"}
          </span>
        </div>
        <p className={u.sub}>
          Your {quotes.length} holdings, end of day on NSE. <strong>{up}</strong> up · <strong>{down}</strong> down.
        </p>
        <div className={s.breadth} role="img" aria-label={`${up} up, ${down} down, ${quotes.length - up - down} flat`}>
          <span style={{ flexGrow: up }} data-dir="up" />
          <span style={{ flexGrow: quotes.length - up - down }} data-dir="flat" />
          <span style={{ flexGrow: down }} data-dir="down" />
        </div>
      </header>

      <section className={u.section} aria-labelledby="movers">
        <div className={s.sectionRow}>
          <h2 id="movers" className={u.sectionHead}>
            Top movers
          </h2>
          <div className={u.segment} role="group" aria-label="Movers">
            {(["gainers", "losers", "volume"] as const).map((k) => (
              <button key={k} type="button" aria-pressed={movers === k} onClick={() => setMovers(k)}>
                {k === "gainers" ? "Up" : k === "losers" ? "Down" : "Volume"}
              </button>
            ))}
          </div>
        </div>
        <div className={s.movers}>
          {moverList.length === 0 && <p className={u.sub}>No stock {movers === "gainers" ? "rose" : "fell"} on the last session.</p>}
          {moverList.map((q, i) => (
            <Link key={`${movers}-${q.symbol}`} href={`/markets/${q.symbol}`} className={`${s.mover} press`} style={{ animationDelay: `${i * 50}ms` }}>
              <span className="ticker">{q.symbol}</span>
              <span className={s.moverName}>{q.name}</span>
              <Spark values={q.spark} width={120} height={34} dir={direction(q.pct_change)} fluid />
              {movers === "volume" ? (
                <span className={`num ${s.moverBig}`}>
                  <CountUp value={q.vol_ratio ?? 0} format={(v) => times(v)} />
                  <span className={s.moverSmall}> vs 20-day avg</span>
                </span>
              ) : (
                <span className={`num ${s.moverBig}`} data-dir={direction(q.pct_change)}>
                  <CountUp value={q.pct_change ?? 0} format={(v) => pct(v, 2)} />
                </span>
              )}
            </Link>
          ))}
        </div>
      </section>

      <section className={u.section} aria-labelledby="watch">
        <div className={s.sectionRow}>
          <h2 id="watch" className={u.sectionHead}>
            Watchlist <span>{loaded ? listed.length : ""}</span>
          </h2>
          <button type="button" className={u.textButton} onClick={() => setEditing(true)}>
            <Pencil size={14} strokeWidth={2} aria-hidden="true" style={{ verticalAlign: "-2px", marginRight: 4 }} />
            Edit
          </button>
        </div>
        {listed.length === 0 ? (
          <div className={u.empty}>
            <strong>Your watchlist is empty</strong>
            Pick from your holdings with Edit.
          </div>
        ) : (
          <ul className={s.watch}>
            {listed.map((q, i) => (
              <li key={q.symbol} style={{ animationDelay: `${Math.min(i, 10) * 30}ms` }}>
                <Link href={`/markets/${q.symbol}`} className={`${s.watchRow} press`}>
                  <span className={s.watchWho}>
                    <span className={s.watchName}>{q.name}</span>
                    <span className="ticker">{q.symbol}</span>
                  </span>
                  <Spark values={q.spark} width={64} height={28} dir={direction(q.pct_change)} />
                  <span className={s.watchPrice}>
                    <CountUp className="num" value={q.close} from={q.prev_close ?? q.close} format={rupees} />
                    <Delta value={q.pct_change} />
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
        <p className={s.note}>Sparklines: last 30 sessions. Prices are end-of-day closes from the snapshot, not live quotes.</p>
      </section>

      <Sheet open={editing} label="Edit watchlist" onClose={() => setEditing(false)}>
        <h2 className={sh.title}>Watchlist</h2>
        <p className={sh.sub}>Choose which of your holdings show here. Saved on this device.</p>
        <ul className={s.pickList}>
          {quotes.map((q) => {
            const on = watch.includes(q.symbol);
            return (
              <li key={q.symbol}>
                <button
                  type="button"
                  role="checkbox"
                  aria-checked={on}
                  className={`${s.pick} press`}
                  onClick={() => setWatch((prev) => (on ? prev.filter((x) => x !== q.symbol) : all.filter((x) => x === q.symbol || prev.includes(x))))}
                >
                  <span className={s.box} aria-hidden="true">
                    {on && <Check size={14} strokeWidth={3} />}
                  </span>
                  <span className={s.watchWho}>
                    <span className={s.watchName}>{q.name}</span>
                    <span className="ticker">{q.symbol}</span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
        <div className={s.pickActions}>
          <button type="button" className={u.textButton} onClick={() => setWatch(all)}>
            Select all
          </button>
          <button type="button" className={u.textButton} onClick={() => setWatch([])}>
            Clear
          </button>
        </div>
      </Sheet>
    </div>
  );
}
