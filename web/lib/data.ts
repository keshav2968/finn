// Build-time loader: reads data/seed and config/ from the repo and slims them into what
// the app needs. Runs only on the server (during `next build`), never in the browser.

import fs from "node:fs";
import path from "node:path";
import YAML from "yaml";
import type { InboxData, Item, ManagementCard, PriceSeries, ResultsCard, Tier } from "./types";

// The repo root: web/ sits one level below it. FINN_ROOT overrides (e.g. a CI checkout).
const ROOT = process.env.FINN_ROOT ? path.resolve(process.env.FINN_ROOT) : path.resolve(process.cwd(), "..");

function readJson<T>(rel: string): T | null {
  const file = path.join(ROOT, rel);
  if (!fs.existsSync(file)) return null;
  return JSON.parse(fs.readFileSync(file, "utf8")) as T;
}

function readYaml<T>(rel: string): T {
  return YAML.parse(fs.readFileSync(path.join(ROOT, rel), "utf8")) as T;
}

interface AppConfig {
  ask: InboxData["ask"];
  sector_hues?: Record<string, number>;
  timezone: string;
  schedule_note: string;
  inbox: {
    windows: { key: string; label: string; hours: number }[];
    default_window: string;
    spark_sessions: number;
    results_metrics: Record<string, string[]>;
    results_checks: string[];
    alert_choices: { price_move_pct: number[]; volume_ratio: number[]; move_z: number[]; hidden_categories?: string[] };
  };
}

interface PushYaml {
  reaction?: { market_close_ist?: string };
  grouping?: { same_day_categories?: string[] };
}

/* eslint-disable @typescript-eslint/no-explicit-any */
type Json = any;

function seedDir(): string {
  const settings = readYaml<{ paths?: { seed_dir?: string } }>("config/settings.yaml");
  return settings.paths?.seed_dir ?? "data/seed";
}

function resultsCards(cards: Json): { bySymbol: Record<string, ResultsCard>; byFiling: Map<string, string> } {
  const bySymbol: Record<string, ResultsCard> = {};
  const byFiling = new Map<string, string>();
  for (const card of Object.values<Json>(cards ?? {})) {
    if (!card || card.status === "unavailable") continue;
    bySymbol[card.symbol] = {
      symbol: card.symbol,
      status: card.status,
      layout: card.layout,
      basis: card.basis,
      periods: card.periods,
      metrics: (card.metrics as Json[]).map((m) => ({
        key: m.key,
        label: m.label,
        main: Boolean(m.main),
        kind: m.kind,
        current: m.current ?? null,
        previous: m.previous ?? null,
        year_ago: m.year_ago ?? null,
        qoq: (m.kind === "margin" ? m.qoq_pp : m.qoq_pct) ?? null,
        yoy: (m.kind === "margin" ? m.yoy_pp : m.yoy_pct) ?? null,
        check: m.check,
        screener: m.screener ?? {},
      })),
      notes: card.notes ?? [],
      formula: card.formula ?? null,
      pdf_url: card.source?.pdf_url ?? null,
      page: card.source?.page ?? null,
    };
    const ids: string[] = card.source?.filing_ids ?? (card.source?.filing_id ? [card.source.filing_id] : []);
    for (const id of ids) byFiling.set(id, card.symbol);
  }
  return { bySymbol, byFiling };
}

function managementCards(cards: Json): Map<string, ManagementCard> {
  const byFiling = new Map<string, ManagementCard>();
  for (const [id, card] of Object.entries<Json>(cards ?? {})) {
    if (!card || card.status !== "ok") continue;
    byFiling.set(id, {
      severity: card.severity,
      summary: card.summary,
      flags: card.flags ?? [],
      notes: card.notes ?? [],
      people: (card.people as Json[]).map((p) => ({
        name: p.name,
        role: p.role,
        change: p.change,
        direction: p.direction,
        entity: p.entity ?? null,
        at_subsidiary: Boolean(p.at_subsidiary),
        effective_date: p.effective_date ?? null,
        stated_reason: p.stated_reason ?? null,
        prior_roles: p.prior_roles ?? [],
        tenure: p.tenure ?? null,
        flags: p.flags ?? [],
      })),
    });
  }
  return byFiling;
}

export interface LoadOptions {
  /** Every filing in the snapshot (about 60 days), not just the widest window. */
  allItems?: boolean;
  /** Only this company's filings: a stock page needs nothing else. */
  symbol?: string;
}

export function loadInbox(opts: LoadOptions = {}): InboxData {
  const cfg = readYaml<AppConfig>("config/app.yaml");
  const push = readYaml<PushYaml>("config/push.yaml");
  const seed = seedDir();

  const feed = readJson<Json>(`${seed}/push/feed.json`);
  if (!feed) throw new Error(`${seed}/push/feed.json is missing: run scripts/build_push.py`);
  const manifest = readJson<Json>(`${seed}/manifest.json`);
  const results = resultsCards(readJson<Json>(`${seed}/push/results_cards.json`)?.cards);
  const management = managementCards(readJson<Json>(`${seed}/push/management_cards.json`)?.cards);

  const maxHours = Math.max(...cfg.inbox.windows.map((w) => w.hours));
  const snapshot = Date.parse(feed.snapshot_at);
  const earliest = snapshot - maxHours * 3_600_000;

  const items: Item[] = (feed.items as Json[])
    .filter((it) => opts.allItems || Date.parse(it.datetime) > earliest)
    .filter((it) => !opts.symbol || it.symbol === opts.symbol)
    .map((it) => ({
      id: it.id,
      symbol: it.symbol,
      datetime: it.datetime,
      headline: it.headline,
      category: it.category,
      category_label: it.category_label,
      kind: it.kind,
      pending: Boolean(it.pending_llm),
      method: it.classified_by?.method ?? "rule",
      score: it.score,
      tier: it.tier as Tier,
      reasons: it.reasons ?? [],
      score_parts: it.score_parts ?? [],
      reaction: it.reaction ?? null,
      group_key: it.group_key,
      pdf_url: it.pdf_url ?? null,
      results_symbol: results.byFiling.get(it.id) ?? null,
      management: management.get(it.id) ?? null,
    }));

  // Price series trimmed to the sessions the widest window can reach, plus enough
  // earlier sessions to draw a sparkline for the first alert in that window.
  const companies: InboxData["companies"] = {};
  const prices: Record<string, PriceSeries> = {};
  for (const c of (manifest?.companies as Json[]) ?? []) {
    if (!c.in_portfolio) continue;
    companies[c.symbol] = { name: c.name, sector: c.sector ?? null };
    const rec = readJson<Json>(`${seed}/prices/${c.symbol}.json`);
    const s = rec?.series;
    if (!s?.date?.length) continue;
    const first = s.date.findIndex((d: string) => Date.parse(`${d}T23:59:59+05:30`) > earliest);
    const at = Math.max(0, (first < 0 ? s.date.length : first) - cfg.inbox.spark_sessions);
    prices[c.symbol] = {
      date: s.date.slice(at),
      close: s.close.slice(at),
      pct_change: s.pct_change.slice(at),
      vol_ratio: s.vol_ratio.slice(at),
      move_z: s.move_z.slice(at),
      volume_avg_window: rec.params?.volume_avg_window ?? 20,
    };
  }
  for (const [sym, name] of Object.entries<string>(feed.companies ?? {})) {
    companies[sym] ??= { name, sector: null };
  }

  return {
    snapshot_at: feed.snapshot_at,
    prices_as_of: manifest?.as_of ?? null,
    generated_at: feed.generated_at,
    timezone: cfg.timezone,
    schedule_note: cfg.schedule_note,
    windows: cfg.inbox.windows,
    default_window: cfg.inbox.default_window,
    spark_sessions: cfg.inbox.spark_sessions,
    results_metrics: cfg.inbox.results_metrics,
    results_checks: cfg.inbox.results_checks,
    tier_labels: feed.rules.tier_labels,
    tiers: feed.rules.tiers,
    rules: feed.rules.alerts,
    alert_choices: {
      price_move_pct: cfg.inbox.alert_choices.price_move_pct,
      volume_ratio: cfg.inbox.alert_choices.volume_ratio,
      move_z: cfg.inbox.alert_choices.move_z,
      categories: Object.entries<Json>(feed.rules.categories ?? {})
        .filter(([key]) => !(cfg.inbox.alert_choices.hidden_categories ?? []).includes(key))
        .map(([key, c]) => ({ key, label: c.label ?? key })),
    },
    market_close: push.reaction?.market_close_ist ?? "15:30",
    same_day_categories: push.grouping?.same_day_categories ?? [],
    companies,
    items,
    prices,
    results: results.bySymbol,
    ask: cfg.ask,
    sector_hues: cfg.sector_hues ?? {},
    logos: logoSymbols(),
  };
}

/** Symbols with a company logo saved by scripts/fetch_logos.py (web/public/logos/SYMBOL.png).
 *  Read at build time, so the app only ever asks its own domain for a logo that exists. */
export function logoSymbols(): string[] {
  const dir = path.join(ROOT, "web", "public", "logos");
  if (!fs.existsSync(dir)) return [];
  return fs
    .readdirSync(dir)
    .filter((f) => /^[A-Z0-9&-]+\.png$/.test(f))
    .map((f) => f.slice(0, -4))
    .sort();
}

/** Sector hues for the monogram fallback, for pages that don't load the whole inbox. */
export function loadSectorHues(): Record<string, number> {
  return readYaml<AppConfig>("config/app.yaml").sector_hues ?? {};
}

/** Snapshot times for the footer and status lines (tiny, safe to load in the root layout). */
export function loadMeta(): { snapshot_at: string; prices_as_of: string | null } {
  const seed = seedDir();
  const feed = readJson<Json>(`${seed}/push/feed.json`);
  const manifest = readJson<Json>(`${seed}/manifest.json`);
  return { snapshot_at: feed?.snapshot_at ?? "", prices_as_of: manifest?.as_of ?? null };
}

// ---------------------------------------------------------------- markets

export interface Quote {
  symbol: string;
  name: string;
  sector: string | null;
  size: string | null;
  as_of: string;
  close: number;
  prev_close: number | null;
  pct_change: number | null;
  volume: number | null;
  volume_avg: number | null;
  vol_ratio: number | null;
  move_z: number | null;
  high_52w: number | null;
  low_52w: number | null;
  returns_pct: Record<string, number | null>;
  spark: number[]; // last `spark` closes, oldest first
}

export interface StockSeries {
  date: string[];
  close: number[];
  volume: number[];
  pct_change: (number | null)[];
}

function quoteOf(c: Json, rec: Json, sparkN: number): Quote | null {
  const l = rec?.latest;
  const s = rec?.series;
  if (!l || l.close == null || !s?.close?.length) return null;
  return {
    symbol: c.symbol,
    name: c.name,
    sector: c.sector ?? null,
    size: c.size ?? null,
    as_of: l.as_of,
    close: l.close,
    prev_close: l.prev_close ?? null,
    pct_change: l.pct_change ?? null,
    volume: l.volume ?? null,
    volume_avg: l.volume_avg ?? null,
    vol_ratio: l.vol_ratio ?? null,
    move_z: l.move_z ?? null,
    high_52w: l.high_52w ?? null,
    low_52w: l.low_52w ?? null,
    returns_pct: l.returns_pct ?? {},
    spark: (s.close as (number | null)[]).slice(-sparkN).filter((v): v is number => v !== null),
  };
}

/** Latest quote and a short sparkline for every portfolio company (Markets tab). */
export function loadQuotes(sparkN = 30): Quote[] {
  const seed = seedDir();
  const manifest = readJson<Json>(`${seed}/manifest.json`);
  const out: Quote[] = [];
  for (const c of (manifest?.companies as Json[]) ?? []) {
    if (!c.in_portfolio) continue;
    const q = quoteOf(c, readJson<Json>(`${seed}/prices/${c.symbol}.json`), sparkN);
    if (q) out.push(q);
  }
  return out;
}

/** One company's full end-of-day history (about a year) for the stock page. */
export function loadStock(symbol: string): { quote: Quote; series: StockSeries } | null {
  const seed = seedDir();
  const manifest = readJson<Json>(`${seed}/manifest.json`);
  const c = ((manifest?.companies as Json[]) ?? []).find((x) => x.symbol === symbol);
  const rec = readJson<Json>(`${seed}/prices/${symbol}.json`);
  if (!c || !rec?.series) return null;
  const quote = quoteOf(c, rec, 30);
  if (!quote) return null;
  const s = rec.series;
  const keep = (s.date as string[]).map((_, i) => s.close[i] !== null);
  return {
    quote,
    series: {
      date: (s.date as string[]).filter((_, i) => keep[i]),
      close: (s.close as number[]).filter((_, i) => keep[i]),
      volume: (s.volume as (number | null)[]).filter((_, i) => keep[i]).map((v) => v ?? 0),
      pct_change: (s.pct_change as (number | null)[]).filter((_, i) => keep[i]),
    },
  };
}

export function portfolioSymbols(): string[] {
  const manifest = readJson<Json>(`${seedDir()}/manifest.json`);
  return ((manifest?.companies as Json[]) ?? []).filter((c) => c.in_portfolio).map((c) => c.symbol);
}
