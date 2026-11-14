// Build-time loader: reads data/seed and config/ from the repo and slims them into what
// the inbox needs. Runs only on the server (during `next build`), never in the browser.

import fs from "node:fs";
import path from "node:path";
import YAML from "yaml";
import type { InboxData, Item, ManagementLine, PriceSeries, ResultsLine, Tier } from "./types";

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
  timezone: string;
  schedule_note: string;
  inbox: {
    windows: { key: string; label: string; hours: number }[];
    default_window: string;
    max_reasons: number;
    results_metrics: Record<string, string[]>;
    results_checks: string[];
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

function resultsLines(cards: Json, cfg: AppConfig): Map<string, ResultsLine> {
  // filing id -> the company's results line (only figures that passed a check)
  const byFiling = new Map<string, ResultsLine>();
  for (const card of Object.values<Json>(cards ?? {})) {
    if (!card || card.status === "unavailable") continue;
    const wanted = cfg.inbox.results_metrics[card.layout] ?? [];
    const metrics = wanted
      .map((key) => (card.metrics as Json[]).find((m) => m.key === key))
      .filter((m) => m && m.current !== null && cfg.inbox.results_checks.includes(m.check?.current))
      .map((m) => ({ key: m.key, label: m.label, current: m.current, yoy_pct: m.yoy_pct ?? null }));
    const line: ResultsLine = { symbol: card.symbol, status: card.status, period: card.periods?.current ?? "", metrics };
    const ids: string[] = card.source?.filing_ids ?? (card.source?.filing_id ? [card.source.filing_id] : []);
    for (const id of ids) byFiling.set(id, line);
  }
  return byFiling;
}

function managementLines(cards: Json): Map<string, ManagementLine> {
  const byFiling = new Map<string, ManagementLine>();
  for (const [id, card] of Object.entries<Json>(cards ?? {})) {
    if (!card || card.status !== "ok") continue;
    byFiling.set(id, { severity: card.severity, summary: card.summary, flags: card.flags ?? [] });
  }
  return byFiling;
}

export function loadInbox(): InboxData {
  const cfg = readYaml<AppConfig>("config/app.yaml");
  const push = readYaml<PushYaml>("config/push.yaml");
  const seed = seedDir();

  const feed = readJson<Json>(`${seed}/push/feed.json`);
  if (!feed) throw new Error(`${seed}/push/feed.json is missing: run scripts/build_push.py`);
  const manifest = readJson<Json>(`${seed}/manifest.json`);
  const results = resultsLines(readJson<Json>(`${seed}/push/results_cards.json`)?.cards, cfg);
  const management = managementLines(readJson<Json>(`${seed}/push/management_cards.json`)?.cards);

  const maxHours = Math.max(...cfg.inbox.windows.map((w) => w.hours));
  const snapshot = Date.parse(feed.snapshot_at);
  const earliest = snapshot - maxHours * 3_600_000;

  const items: Item[] = (feed.items as Json[])
    .filter((it) => Date.parse(it.datetime) > earliest)
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
      reaction: it.reaction ?? null,
      group_key: it.group_key,
      pdf_url: it.pdf_url ?? null,
      results: results.get(it.id) ?? null,
      management: management.get(it.id) ?? null,
    }));

  // Price series trimmed to the sessions the widest window can reach.
  const companies: InboxData["companies"] = {};
  const prices: Record<string, PriceSeries> = {};
  for (const c of (manifest?.companies as Json[]) ?? []) {
    if (!c.in_portfolio) continue;
    companies[c.symbol] = { name: c.name, sector: c.sector ?? null };
    const rec = readJson<Json>(`${seed}/prices/${c.symbol}.json`);
    const s = rec?.series;
    if (!s?.date?.length) continue;
    const from = s.date.findIndex((d: string) => Date.parse(`${d}T23:59:59+05:30`) > earliest);
    const at = from < 0 ? s.date.length : from;
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
    max_reasons: cfg.inbox.max_reasons,
    tier_labels: feed.rules.tier_labels,
    rules: feed.rules.alerts,
    market_close: push.reaction?.market_close_ist ?? "15:30",
    same_day_categories: push.grouping?.same_day_categories ?? [],
    companies,
    items,
    prices,
  };
}
