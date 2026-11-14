"use client";

import { Bell } from "lucide-react";
import { croreShort, day, direction, rupees } from "@/lib/format";
import { exitFlag, resultsHeadlines, sparkValues } from "@/lib/present";
import type { Card, InboxData, PriceAlert } from "@/lib/types";
import Delta from "./Delta";
import Spark from "./Spark";
import SwipeRow from "./SwipeRow";
import s from "./cards.module.css";

// Every card leads with the company, then the one thing that changed, then a quiet
// meta line. Detail lives in the sheet.

function Sep() {
  return (
    <span className="sep" aria-hidden="true">
      ·
    </span>
  );
}

export function FilingCard({
  card,
  data,
  onOpen,
  onDone,
}: {
  card: Card;
  data: InboxData;
  onOpen: () => void;
  onDone: () => void;
}) {
  const { lead } = card;
  const name = data.companies[lead.symbol]?.name ?? lead.symbol;
  const heads = resultsHeadlines(card, data);
  const exit = exitFlag(card);
  const r = lead.reaction;

  return (
    <SwipeRow label={`${name}: ${lead.headline}. Open details`} onOpen={onOpen} onDone={onDone}>
      <div className={s.head}>
        <div className={s.who}>
          <span className={s.name}>{name}</span>
          <span className={`ticker ${s.ticker}`}>{lead.symbol}</span>
        </div>
        {exit ? (
          <span className={s.flag}>{exit}</span>
        ) : (
          r &&
          r.pct_change !== null && (
            <span className={s.reaction} aria-label={`Stock ${r.pct_change > 0 ? "rose" : "fell"} on ${day(r.date)}`}>
              <Delta value={r.pct_change} />
              <span className={s.reactionCaption}>Stock, {day(r.date)}</span>
            </span>
          )
        )}
      </div>

      {heads.length > 0 ? (
        <div className={s.figures}>
          <span className={s.leadFigure}>
            <span className={s.figureLabel}>{heads[0].label}</span>
            <span className="num">{croreShort(heads[0].value)}</span>
            <Delta value={heads[0].yoy} digits={1} suffix="YoY" />
          </span>
          {heads.slice(1).map((h) => (
            <span key={h.label} className={s.minorFigure}>
              <span className={s.figureLabel}>{h.label}</span>
              <Delta value={h.yoy} digits={1} />
            </span>
          ))}
        </div>
      ) : (
        <p className={s.headline}>{lead.headline}</p>
      )}

      <p className={s.meta}>
        {card.alert && <Bell size={12} strokeWidth={2} aria-label="Alert" className={s.metaIcon} />}
        {lead.category_label}
        {heads.length > 0 && data.results[card.results_symbol!] && (
          <>
            <Sep />
            {data.results[card.results_symbol!].periods.current} quarter
          </>
        )}
        <Sep />
        {day(lead.datetime)}
        {card.members.length > 1 && (
          <>
            <Sep />
            {card.members.length} filings
          </>
        )}
      </p>
    </SwipeRow>
  );
}

export function PriceCard({
  alert,
  data,
  onOpen,
  onDone,
}: {
  alert: PriceAlert;
  data: InboxData;
  onOpen: () => void;
  onDone: () => void;
}) {
  const values = sparkValues(data.prices[alert.symbol], alert.date, data.spark_sessions);
  return (
    <SwipeRow label={`${alert.name}, price alert. Open details`} onOpen={onOpen} onDone={onDone}>
      <div className={s.head}>
        <div className={s.who}>
          <span className={s.name}>{alert.name}</span>
          <span className={`ticker ${s.ticker}`}>{alert.symbol}</span>
        </div>
        <Spark values={values} width={72} height={28} dir={direction(alert.pct_change)} />
      </div>
      <div className={s.priceLine}>
        <span className={`num ${s.price}`}>{rupees(alert.close)}</span>
        <Delta value={alert.pct_change} />
        <span className={s.on}>on {day(alert.date)}</span>
      </div>
    </SwipeRow>
  );
}
