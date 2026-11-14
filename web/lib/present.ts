// What a row shows: the one reason an alert fired, the one key figure, the sparkline.
// Everything else lives in the detail sheet.

import type { AlertRules, Card, InboxData, PriceAlert, PriceSeries } from "./types.ts";

export type KeyFigure =
  | { kind: "move"; value: number; caption: string } // price movement: coloured, with arrow
  | { kind: "change"; value: number; caption: string } // a reported figure's change: neutral
  | { kind: "flag"; label: string }
  | null;

const EXIT_FLAGS = new Set(["ceo_exit", "cfo_exit"]);

export function keyFigure(card: Card, data: InboxData, dayLabel: (d: string) => string): KeyFigure {
  const exit = card.management?.flags.find((f) => EXIT_FLAGS.has(f.code));
  if (exit) return { kind: "flag", label: exit.label };

  const res = card.results_symbol ? data.results[card.results_symbol] : undefined;
  if (res) {
    for (const key of data.results_metrics[res.layout] ?? []) {
      const m = res.metrics.find((x) => x.key === key);
      if (m && m.yoy !== null && data.results_checks.includes(m.check.current)) {
        return { kind: "change", value: m.yoy, caption: `${m.label} YoY` };
      }
    }
  }

  const r = card.lead.reaction;
  if (r && r.pct_change !== null) return { kind: "move", value: r.pct_change, caption: `Stock, ${dayLabel(r.date)}` };
  return null;
}

/** The single reason a price alert fired, strongest trigger first. */
export function alertReason(alert: PriceAlert, rules: AlertRules, avgWindow: number): string {
  if (alert.triggers.includes("volume_spike") && alert.vol_ratio !== null) {
    return `Volume ${alert.vol_ratio.toFixed(1)}× ${avgWindow}-day avg`;
  }
  if (alert.triggers.includes("move_z") && alert.move_z !== null) {
    return `${Math.abs(alert.move_z).toFixed(1)}× usual swing`;
  }
  return `Moved over ${rules.price_move_pct}%`;
}

/** Closing prices for the `n` sessions ending on `date` (oldest first). */
export function sparkValues(series: PriceSeries | undefined, date: string, n: number): number[] {
  if (!series) return [];
  const end = series.date.indexOf(date);
  if (end < 0) return [];
  return series.close.slice(Math.max(0, end - n + 1), end + 1).filter((v): v is number => v !== null);
}
