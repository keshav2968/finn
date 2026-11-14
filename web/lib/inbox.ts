// Inbox logic, run in the browser so the window chips (and later the alert settings)
// re-evaluate instantly. Mirrors push/priority.py (cards, lead choice, order) and
// push/alerts.py (price and filing alerts); lib/inbox.test.ts checks it against
// the alerts.json the pipeline wrote for the default window.

import type { AlertRules, Card, InboxData, InboxView, Item, PriceAlert, PriceSeries } from "./types.ts";

const METHOD_RANK: Record<string, number> = { rule: 0, llm: 1, context: 2, pending: 3 };

export function windowRange(snapshotAt: string, hours: number): { start: number; end: number } {
  const end = Date.parse(snapshotAt);
  return { start: end - hours * 3_600_000, end };
}

export function sessionClose(day: string, marketClose: string): number {
  return Date.parse(`${day}T${marketClose}:00+05:30`);
}

function ts(item: Item): number {
  return Date.parse(item.datetime);
}

export function buildCards(items: Item[], sameDayCategories: string[]): Omit<Card, "alert">[] {
  const groups = new Map<string, Item[]>();
  for (const item of items) {
    const list = groups.get(item.group_key);
    if (list) list.push(item);
    else groups.set(item.group_key, [item]);
  }
  const cards: Omit<Card, "alert">[] = [];
  for (const [key, members] of groups) {
    const sameDay = sameDayCategories.includes(members[0].category) && !members[0].pending;
    members.sort((a, b) => {
      if (b.score !== a.score) return b.score - a.score;
      if (sameDay) {
        const m = (METHOD_RANK[a.method] ?? 9) - (METHOD_RANK[b.method] ?? 9);
        return m !== 0 ? m : ts(a) - ts(b);
      }
      return ts(b) - ts(a);
    });
    cards.push({
      key: `card:${key}`,
      lead: members[0],
      members,
      results: members.find((m) => m.results)?.results ?? null,
      management: members.find((m) => m.management)?.management ?? null,
    });
  }
  cards.sort((a, b) => b.lead.score - a.lead.score || ts(b.lead) - ts(a.lead));
  return cards;
}

export function isFilingAlert(lead: Item, rules: AlertRules): boolean {
  const min = rules.filing_min_score;
  return (
    rules.filing_categories.includes(lead.category) &&
    !lead.pending &&
    (min === null || lead.score >= min)
  );
}

export function priceAlerts(
  symbol: string,
  name: string,
  series: PriceSeries,
  rules: AlertRules,
  start: number,
  end: number,
  marketClose: string,
): PriceAlert[] {
  const out: PriceAlert[] = [];
  series.date.forEach((day, i) => {
    const close = sessionClose(day, marketClose);
    if (!(start < close && close <= end)) return;
    const pct = series.pct_change[i] ?? null;
    const vr = series.vol_ratio[i] ?? null;
    const z = series.move_z[i] ?? null;
    const reasons: string[] = [];
    const triggers: PriceAlert["triggers"] = [];
    if (rules.price_move_pct !== null && pct !== null && Math.abs(pct) >= rules.price_move_pct) {
      triggers.push("price_move");
      reasons.push(`${pct > 0 ? "Up" : "Down"} ${Math.abs(pct).toFixed(1)}% on the day`);
    }
    if (rules.move_z !== null && z !== null && Math.abs(z) >= rules.move_z) {
      triggers.push("move_z");
      reasons.push(`${Math.abs(z).toFixed(1)}σ move for this stock`);
    }
    if (rules.volume_ratio !== null && vr !== null && vr >= rules.volume_ratio) {
      triggers.push("volume_spike");
      reasons.push(`Volume ${vr.toFixed(1)}× its ${series.volume_avg_window}-day average`);
    }
    if (!triggers.length) return;
    out.push({
      key: `${symbol}:${day}:price`,
      symbol,
      name,
      date: day,
      close: series.close[i] ?? null,
      pct_change: pct,
      vol_ratio: vr,
      move_z: z,
      triggers,
      reasons,
      severity: triggers.length > 1 ? "high" : "normal",
    });
  });
  return out;
}

export function buildInbox(data: InboxData, hours: number, rules: AlertRules = data.rules): InboxView {
  const { start, end } = windowRange(data.snapshot_at, hours);
  const inWindow = data.items.filter((it) => {
    const t = ts(it);
    return start < t && t <= end;
  });
  const cards: Card[] = buildCards(inWindow, data.same_day_categories).map((c) => ({
    ...c,
    alert: isFilingAlert(c.lead, rules),
  }));

  const priceList: PriceAlert[] = [];
  for (const [symbol, series] of Object.entries(data.prices)) {
    const name = data.companies[symbol]?.name ?? symbol;
    priceList.push(...priceAlerts(symbol, name, series, rules, start, end, data.market_close));
  }
  // Newest session first; within a day, high severity first, then the bigger move.
  priceList.sort(
    (a, b) =>
      b.date.localeCompare(a.date) ||
      Number(b.severity === "high") - Number(a.severity === "high") ||
      Math.abs(b.pct_change ?? 0) - Math.abs(a.pct_change ?? 0),
  );

  return {
    from: new Date(start).toISOString(),
    to: new Date(end).toISOString(),
    priceAlerts: priceList,
    needs: cards.filter((c) => c.lead.tier === "needs_attention"),
    worth: cards.filter((c) => c.lead.tier === "worth_knowing"),
    routine: cards.filter((c) => c.lead.tier === "routine"),
    filingCount: inWindow.length,
  };
}

/** Ids of everything that pinged: what the alert badge counts. */
export function alertKeys(view: InboxView): string[] {
  return [
    ...view.priceAlerts.map((a) => a.key),
    ...[...view.needs, ...view.worth, ...view.routine].filter((c) => c.alert).map((c) => c.key),
  ];
}
