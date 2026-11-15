// What a story shows: a headline that leads with the news, an impact label, and the
// stock's move. Everything here is picked or formatted, never computed by a model.

import { croreShort, pct } from "@/lib/format";
import { exitFlag, resultsHeadlines } from "@/lib/present";
import type { Card, InboxData, Tier } from "@/lib/types";

export const IMPACT: Record<Tier, string> = {
  needs_attention: "High impact",
  worth_knowing: "Notable",
  routine: "Routine",
};

/** Results cards lead with the figure that moved most; everything else with the filing headline. */
export function storyHeadline(card: Card, data: InboxData): string {
  const heads = resultsHeadlines(card, data);
  const res = card.results_symbol ? data.results[card.results_symbol] : undefined;
  if (heads.length && res) {
    const h = heads[0];
    return `${res.periods.current} quarter: ${h.label} ${croreShort(h.value)}, ${pct(h.yoy, 1)} YoY`;
  }
  return card.lead.headline;
}

export function storyFlag(card: Card): string | null {
  return exitFlag(card);
}

/** The latest session's move for a symbol: what a ticker chip shows. */
export function dayMove(data: InboxData, symbol: string): { pct: number | null; date: string | null } {
  const s = data.prices[symbol];
  if (!s || !s.date.length) return { pct: null, date: null };
  const i = s.date.length - 1;
  return { pct: s.pct_change[i], date: s.date[i] };
}

/** Closing prices for a story's chart: the window's sessions, with the filing's session marked. */
export function storyChart(data: InboxData, card: Card): { values: number[]; mark: number } | null {
  const s = data.prices[card.lead.symbol];
  if (!s) return null;
  const vals: number[] = [];
  const dates: string[] = [];
  s.close.forEach((v, i) => {
    if (v !== null) {
      vals.push(v);
      dates.push(s.date[i]);
    }
  });
  if (vals.length < 3) return null;
  const day = card.lead.reaction?.date ?? card.lead.datetime.slice(0, 10);
  let mark = dates.findIndex((d) => d >= day);
  if (mark < 0) mark = dates.length - 1;
  return { values: vals, mark };
}
