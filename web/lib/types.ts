// Shapes the app works with. Built at build time by lib/data.ts from data/seed
// (see docs/data-contract.md for the files they come from).

export type Tier = "needs_attention" | "worth_knowing" | "routine";
export type Check = "verified" | "mismatch" | "unchecked" | "screener" | "missing";

export interface AlertRules {
  price_move_pct: number | null;
  volume_ratio: number | null;
  move_z: number | null;
  filing_categories: string[];
  filing_min_score: number | null;
}

export interface Reaction {
  date: string;
  pct_change: number | null;
  move_z: number | null;
  vol_ratio: number | null;
}

export interface ResultsMetric {
  key: string;
  label: string;
  main: boolean;
  kind: "amount" | "margin";
  current: number | null;
  previous: number | null;
  year_ago: number | null;
  qoq: number | null; // % for amounts, percentage points for margins
  yoy: number | null;
  check: Record<"current" | "previous" | "year_ago", Check>;
  screener: Partial<Record<"current" | "previous" | "year_ago", number | null>>;
}

export interface ResultsCard {
  symbol: string;
  status: "verified" | "partial" | "mismatch" | "screener_only" | "unavailable";
  layout: "standard" | "lender";
  basis: string;
  periods: { current: string; previous: string; year_ago: string };
  metrics: ResultsMetric[];
  notes: string[];
  formula: string | null;
  pdf_url: string | null;
  page: number | null;
}

export interface Person {
  name: string;
  role: string;
  change: string;
  direction: "joining" | "leaving" | "continuing";
  entity: string | null;
  at_subsidiary: boolean;
  effective_date: string | null;
  stated_reason: string | null;
  prior_roles: string[];
  tenure: string | null;
  flags: { code: string; label: string }[];
}

export interface ManagementCard {
  severity: "high" | "normal" | "low";
  summary: string;
  people: Person[];
  flags: { code: string; label: string; name: string }[];
  notes: string[];
}

export interface Item {
  id: string;
  symbol: string;
  datetime: string;
  headline: string;
  category: string;
  category_label: string;
  kind: "event" | "notice";
  pending: boolean;
  method: string;
  score: number;
  tier: Tier;
  reasons: string[];
  score_parts: { label: string; delta: number }[];
  reaction: Reaction | null;
  group_key: string;
  pdf_url: string | null;
  results_symbol: string | null; // this filing is covered by that company's results card
  management: ManagementCard | null;
}

export interface PriceSeries {
  date: string[];
  close: (number | null)[];
  pct_change: (number | null)[];
  vol_ratio: (number | null)[];
  move_z: (number | null)[];
  volume_avg_window: number;
}

export interface WindowOption {
  key: string;
  label: string;
  hours: number;
}

export interface InboxData {
  snapshot_at: string;
  prices_as_of: string | null;
  generated_at: string;
  timezone: string;
  schedule_note: string;
  windows: WindowOption[];
  default_window: string;
  spark_sessions: number;
  results_metrics: Record<string, string[]>;
  results_checks: string[];
  tier_labels: Record<Tier, string>;
  tiers: { needs_attention: number; worth_knowing: number };
  rules: AlertRules;
  market_close: string;
  same_day_categories: string[];
  companies: Record<string, { name: string; sector: string | null }>;
  items: Item[];
  prices: Record<string, PriceSeries>;
  results: Record<string, ResultsCard>;
  ask: AskConfig;
}

export interface AskConfig {
  max_questions: number;
  [category: string]: string[] | number;
}

export interface Card {
  key: string; // "card:" + group_key, the done-state key
  lead: Item;
  members: Item[];
  alert: boolean;
  results_symbol: string | null;
  management: ManagementCard | null;
}

export interface PriceAlert {
  key: string; // the alert id, the done-state key
  symbol: string;
  name: string;
  date: string;
  close: number | null;
  pct_change: number | null;
  vol_ratio: number | null;
  move_z: number | null;
  triggers: ("price_move" | "move_z" | "volume_spike")[];
  reasons: string[];
  severity: "high" | "normal";
}

export interface InboxView {
  from: string;
  to: string;
  priceAlerts: PriceAlert[];
  needs: Card[];
  worth: Card[];
  routine: Card[];
  filingCount: number;
}
