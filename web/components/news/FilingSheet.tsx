"use client";

import Link from "next/link";
import { ChartCandlestick, ExternalLink } from "lucide-react";
import type { Card, InboxData, PriceAlert } from "@/lib/types";
import { FilingDetail, PriceDetail } from "../Details";
import Sheet from "../Sheet";
import sh from "../sheet.module.css";

export type Opened = { type: "card"; card: Card } | { type: "price"; alert: PriceAlert } | null;

// The detail sheet for a story or an alert, with the filing PDF and the stock's chart one tap away.
export default function FilingSheet({ open, data, onClose, hideChartLink }: { open: Opened; data: InboxData; onClose: () => void; hideChartLink?: boolean }) {
  const symbol = open?.type === "card" ? open.card.lead.symbol : open?.alert.symbol;
  const label =
    open?.type === "price" ? `${open.alert.name} price alert` : open ? (data.companies[open.card.lead.symbol]?.name ?? open.card.lead.symbol) : "";
  return (
    <Sheet
      open={open !== null}
      label={label}
      onClose={onClose}
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
            {symbol && !hideChartLink && (
              <Link className={`${sh.primary} press`} href={`/markets/${encodeURIComponent(symbol)}`} onClick={onClose}>
                <ChartCandlestick size={16} strokeWidth={2} aria-hidden="true" /> {symbol} chart
              </Link>
            )}
          </>
        )
      }
    >
      {open?.type === "price" && <PriceDetail key={open.alert.key} alert={open.alert} data={data} />}
      {open?.type === "card" && <FilingDetail key={open.card.key} card={open.card} data={data} />}
    </Sheet>
  );
}
