// What a card shows: its headline figures, the price-alert context, the sparkline,
// and the questions its "Ask" buttons offer. Everything else lives in the detail sheet.

import type { AskConfig, Card, InboxData, PriceAlert, PriceSeries, ResultsMetric } from "./types.ts";

export interface Headline {
  label: string; // "PAT"
  value: number | null; // ₹ crore, for the lead metric
  yoy: number;
}

/** Results figures for a card: the checked metrics, the one that moved most first. */
export function resultsHeadlines(card: Card, data: InboxData): Headline[] {
  const res = card.results_symbol ? data.results[card.results_symbol] : undefined;
  if (!res) return [];
  const picked: ResultsMetric[] = [];
  for (const key of data.results_metrics[res.layout] ?? []) {
    const m = res.metrics.find((x) => x.key === key);
    if (m && m.yoy !== null && m.kind === "amount" && data.results_checks.includes(m.check.current)) picked.push(m);
  }
  return picked
    .sort((a, b) => Math.abs(b.yoy ?? 0) - Math.abs(a.yoy ?? 0))
    .map((m) => ({ label: m.label, value: m.current, yoy: m.yoy as number }));
}

export const EXIT_FLAGS = new Set(["ceo_exit", "cfo_exit"]);

export function exitFlag(card: Card): string | null {
  return card.management?.flags.find((f) => EXIT_FLAGS.has(f.code))?.label ?? null;
}

/** Closing prices for the `n` sessions ending on `date` (oldest first). */
export function sparkValues(series: PriceSeries | undefined, date: string, n: number): number[] {
  if (!series) return [];
  const end = series.date.indexOf(date);
  if (end < 0) return [];
  return series.close.slice(Math.max(0, end - n + 1), end + 1).filter((v): v is number => v !== null);
}

/** Every reason a price alert fired, in words (for the detail sheet). */
export function alertReasons(alert: PriceAlert, avgWindow: number): string[] {
  const out: string[] = [];
  if (alert.triggers.includes("price_move") && alert.pct_change !== null) {
    out.push(`${alert.pct_change > 0 ? "Rose" : "Fell"} ${Math.abs(alert.pct_change).toFixed(1)}% in one session`);
  }
  if (alert.triggers.includes("volume_spike") && alert.vol_ratio !== null) {
    out.push(`Traded ${alert.vol_ratio.toFixed(1)}× its ${avgWindow}-day average volume`);
  }
  if (alert.triggers.includes("move_z") && alert.move_z !== null) {
    out.push(`A ${Math.abs(alert.move_z).toFixed(1)}× bigger swing than its usual day`);
  }
  return out;
}

/** Fill the configured questions for a category; placeholders without a value drop the question. */
export function askQuestions(ask: AskConfig, category: string, values: Record<string, string | null | undefined>): string[] {
  const list = (Array.isArray(ask[category]) ? ask[category] : ask.default) as string[] | undefined;
  const out: string[] = [];
  for (const q of list ?? []) {
    let ok = true;
    const filled = q.replace(/\{(\w+)\}/g, (_, k: string) => {
      const v = values[k];
      if (!v) ok = false;
      return v ?? "";
    });
    if (ok) out.push(filled);
    if (out.length >= ask.max_questions) break;
  }
  return out;
}

/** Chip tints for the three categories an investor scans for first. Presentation only:
 *  the hues sit apart from green and red (price moves) and the violet accent (controls). */
export const CATEGORY_TONE: Record<string, "results" | "management" | "fund"> = {
  results: "results",
  management_change: "management",
  fund_raise: "fund",
};
