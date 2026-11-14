// Shapes the inbox works with. Built at build time by lib/data.ts from data/seed
// (see docs/data-contract.md for the files they come from).

export type Tier = "needs_attention" | "worth_knowing" | "routine";

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

export interface ResultsLine {
  symbol: string;
  status: string;
  period: string;
  metrics: { key: string; label: string; current: number; yoy_pct: number | null }[];
}

export interface ManagementLine {
  severity: "high" | "normal" | "low";
  summary: string;
  flags: { code: string; label: string; name: string }[];
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
  reaction: Reaction | null;
  group_key: string;
  pdf_url: string | null;
  results: ResultsLine | null;
  management: ManagementLine | null;
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
  max_reasons: number;
  tier_labels: Record<Tier, string>;
  rules: AlertRules;
  market_close: string;
  same_day_categories: string[];
  companies: Record<string, { name: string; sector: string | null }>;
  items: Item[];
  prices: Record<string, PriceSeries>;
}

export interface Card {
  key: string; // "card:" + group_key, the done-state key
  lead: Item;
  members: Item[];
  alert: boolean;
  results: ResultsLine | null;
  management: ManagementLine | null;
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
