# FINN data contract (what the app reads)

All files are static JSON under `data/seed/`, rebuilt by the nightly workflow. Times are
ISO-8601 with `+05:30`. Money is ₹ crore unless a field says otherwise. Any value can be
`null` when the source didn't have it; the app must show "–", not 0.

| File | One per | Built by |
|---|---|---|
| `manifest.json` | snapshot | `scripts/build_seed.py` |
| `prices/SYMBOL.json` | company | `scripts/build_seed.py` |
| `push/feed.json` | snapshot | `scripts/build_push.py` |
| `push/alerts.json` | snapshot | `scripts/build_push.py` |
| `push/results_cards.json` | snapshot | `scripts/build_results_cards.py` |
| `push/management_cards.json` | snapshot | `scripts/build_management_cards.py` |

Joins: a feed item's `id` is the key in `management_cards.cards`; a results card's
`source.filing_ids` lists the feed item ids it covers; feed items with the same
`group_key` are one card in the inbox (show the highest score, "+N related").

```ts
type ISO = string;          // "2026-11-05T17:02:11+05:30" or "2026-11-12"
type Tier = "needs_attention" | "worth_knowing" | "routine";

// manifest.json
interface Manifest {
  generated_at: ISO; as_of: string | null;           // last trading day in the prices
  companies: {
    symbol: string; name: string; sector: string | null;
    size: "large" | "mid" | "small" | null; is_lender: boolean | null;
    in_portfolio: boolean; research_focus: string | null; ad_hoc: boolean;
    bse_code: string | null; primary_view: "consolidated" | "standalone";
    status: Record<"fundamentals" | "prices" | "filings", { state: "ok" | "stale" | "missing"; updated_at: ISO | null; error?: string }>;
  }[];
  warnings: string[];
}

// prices/SYMBOL.json
interface Prices {
  symbol: string; yahoo_symbol: string; as_of: string; fetched_at: ISO;
  latest: {
    as_of: string; close: number; prev_close: number; pct_change: number;
    volume: number; volume_avg: number | null; vol_ratio: number | null; move_z: number | null;
    high_52w: number; low_52w: number; pct_from_52w_high: number;
    returns_pct: { "1w": number | null; "1m": number | null; "3m": number | null; "6m": number | null; "1y": number | null };
  };
  series: {                                           // parallel arrays, oldest first, ~260 sessions
    date: string[]; open: number[]; high: number[]; low: number[]; close: number[]; volume: number[];
    pct_change: (number | null)[]; vol_ratio: (number | null)[]; move_z: (number | null)[];
  };
  params: { volume_avg_window: number; volatility_window: number };
}

// push/feed.json — every portfolio filing in the last 60 days, newest first
interface Feed {
  generated_at: ISO; snapshot_at: ISO; covers: { from: ISO; to: ISO };
  companies: Record<string, string>;                  // symbol -> name
  rules: {
    categories: Record<string, { label: string }>;
    tiers: { needs_attention: number; worth_knowing: number };   // score thresholds (70, 40)
    tier_labels: Record<Tier, string>;
    alerts: AlertRules; digest_window_hours: number;
  };
  counts: { filings: number; by_tier: Record<Tier, number>; by_category: Record<string, number>; by_method: Record<string, number> };
  items: FeedItem[];
}
interface FeedItem {
  id: string; symbol: string; datetime: ISO;
  headline: string;                                   // what the card shows
  title: string; detail: string | null; pdf_url: string | null;
  bse_category: string | null; bse_subcategory: string | null;
  category: string; category_label: string;           // one of the 17 (see rules.categories)
  kind: "event" | "notice";                           // notice = announces something later
  classified_by: { method: "rule" | "context" | "llm" | "pending"; rule: string | null };
  pending_llm: boolean;
  score: number; tier: Tier;                          // 0-100
  reasons: string[];                                  // "why this ranks here"
  score_parts: { label: string; delta: number }[];    // sums to score (before 0-100 clamp)
  reaction: { date: string; pct_change: number | null; move_z: number | null; vol_ratio: number | null } | null;
  group_key: string;
}

// push/alerts.json — alerts for the default window, with the thresholds used
interface AlertRules {
  price_move_pct: number | null; volume_ratio: number | null; move_z: number | null;
  filing_categories: string[]; filing_min_score: number | null;
}
interface AlertsDoc { generated_at: ISO; snapshot_at: ISO; window: { from: ISO; to: ISO }; rules: AlertRules; alerts: Alert[] }
type Alert = PriceAlert | FilingAlert;
interface AlertBase { id: string; symbol: string; name: string; reasons: string[]; reason: string; severity: "high" | "normal" }
interface PriceAlert extends AlertBase {
  type: "price"; date: string;
  triggers: ("price_move" | "volume_spike" | "move_z")[];
  metrics: { close: number | null; pct_change: number | null; vol_ratio: number | null; move_z: number | null };
}
interface FilingAlert extends AlertBase {
  type: "filing"; date: ISO; triggers: ["category"];
  filing_id: string; member_ids: string[]; category: string; tier: Tier; score: number; pdf_url: string | null;
}

// push/results_cards.json — one card per company, its latest results
interface ResultsCards { generated_at: ISO; cards: Record<string, ResultsCard> }
type Check = "verified" | "mismatch" | "unchecked" | "screener" | "missing";
interface ResultsCard {
  symbol: string; name: string;
  layout: "standard" | "lender"; basis: "consolidated" | "standalone"; screener_view: string;
  status: "verified" | "partial" | "mismatch" | "screener_only" | "unavailable";
  periods: { current: string; previous: string; year_ago: string };   // "Sep 2026"
  unit: "₹ crore";
  metrics: Metric[];      // standard: revenue, ebitda, ebitda_margin, pbt, pat, other_income
                          // lender:   nii, ppop, provisions, pat, other_income
  notes: string[];        // OCR corrections, figures taken from screener, unit inferred…
  formula: string | null; // EBITDA definition (standard layout)
  source: { filing_id?: string; filing_ids?: string[]; datetime?: ISO; pdf_url?: string; title?: string;
            page?: number | null; scanned?: boolean; model?: string };
  statement_checks: Record<string, { check: string; ok: boolean; difference?: number; repaired?: string }[]>;
  built_at: ISO;
}
interface Metric {
  key: string; label: string;
  main: boolean;                                      // show in the card; false = detail row
  kind: "amount" | "margin";
  current: number | null; previous: number | null; year_ago: number | null;
  qoq_pct?: number | null; yoy_pct?: number | null;   // amounts (null when the base is ≤ 0)
  qoq_pp?: number | null;  yoy_pp?: number | null;    // margins, percentage points
  check: { current: Check; previous: Check; year_ago: Check };
  screener: { current?: number | null; previous?: number | null; year_ago?: number | null };  // shown on mismatch
}

// push/management_cards.json — keyed by filing id
interface ManagementCards { generated_at: ISO; cards: Record<string, ManagementCard> }
interface ManagementCard {
  filing_id: string; symbol: string; datetime: ISO; title: string; pdf_url: string | null;
  status: "ok" | "no_people" | "unavailable";
  summary: string; severity: "high" | "normal" | "low";
  people: {
    name: string; role: string;
    role_level: "ceo_md" | "cfo" | "chair" | "executive_director" | "independent_director"
              | "non_executive_director" | "senior_management" | "company_secretary" | "auditor" | "other";
    change: "appointment" | "reappointment" | "promotion" | "redesignation" | "resignation"
          | "retirement" | "cessation" | "removal" | "death" | "other";
    direction: "joining" | "leaving" | "continuing";
    entity: string | null; at_subsidiary: boolean;    // role at a subsidiary, not the listed company
    effective_date: string | null; stated_reason: string | null; prior_roles: string[]; tenure: string | null;
    flags: { code: FlagCode; label: string }[];
  }[];
  flags: { code: FlagCode; label: string; name: string }[];
  notes: string[];        // anything dropped because it wasn't in the filing
  source: { text: string; model?: string }; built_at: ISO;
}
type FlagCode = "ceo_exit" | "cfo_exit" | "vague_reason" | "mid_quarter";
```

## Research (`data/seed/research/SYMBOL.json`, built by `scripts/build_research.py`)

```ts
interface Research {
  schema: 1; symbol: string; name: string; generated_at: ISO;
  status: "ok" | "no_transcripts" | "no_promises" | "numbers_only" | "failed";
  error?: string;                                     // only when status is "failed"
  notes: string[];
  numbers: {
    basis: "consolidated" | "standalone"; layout: "standard" | "lender"; unit: "₹ crore";
    latest_quarter: string; latest_fiscal: string;    // "Sep 2026", "Q2 FY27"
    quarters: { period: string; fiscal: string; revenue: number | null; revenue_yoy: number | null;
                net_profit: number | null; net_profit_yoy: number | null;
                ebitda?: number | null; ebitda_margin?: number | null; ebit_margin?: number | null;     // standard
                financing_profit?: number | null; gross_npa_pct?: number | null; net_npa_pct?: number | null }[];  // lender
    years: { period: string; fiscal: string; revenue: number | null; revenue_growth: number | null;
             net_profit: number | null; net_profit_growth: number | null; roce_pct?: number | null; roe_pct?: number | null;
             ebitda_margin?: number | null }[];
    fiscal_year_to_date: { period: string; metrics: Record<string, Actual | null> } | null;
    source: { name: string; url: string | null; fetched_at: ISO | null };
  } | null;
  transcripts: { call: string; quarter: string | null; fiscal: string | null; url: string; error: string | null;
                 management: string[]; passages: number; sent: number; sent_chars: number; promises: number }[];
  ledger: LedgerEntry[];
  summary?: Record<Verdict, number>;
  dropped: { call: string; quote: string; reason: string }[];   // extractions that failed a check
  models: string[];
  sources: { screener: { name: string; url: string | null } | null; transcripts: { call: string; url: string }[] };
}
type Verdict = "Delivered" | "Missed" | "Pending" | "Goalposts moved" | "Unverified";
interface Actual { label: string; value: number; unit: "%"; period: string; quarters: string[]; complete: boolean;
                   basis: string; inputs: Record<string, number | null>; source: string; url: string | null }
interface LedgerEntry {
  id: string; metric: string; metric_label: string; metric_text: string;
  period: string;                                     // "FY27", "H2FY27", "medium_term", "unspecified"
  period_status: string;                              // "in progress (2 of 4 quarters reported)", "period ended", ...
  target: { text: string | null; low: number | null; high: number | null; unit: string | null; basis: string };
  revised: boolean; revision_path: string | null;     // "1.5–3.5% → 1.5–3% → 1–2%"
  statements: { id: string; call: string; fiscal: string | null; speaker: string; quote: string;
                target_text: string | null; basis: string; quote_score: number; source_url: string }[];
  evidence: ({ id: string; kind: "screener" } & Actual |
             { id: string; kind: "transcript"; call: string; fiscal: string | null; speaker: string; passage_id: string; text: string; source_url: string })[];
  check: { comparable: boolean; position: "within" | "above" | "below" | null; actual: number;
           target_low: number; target_high: number; complete: boolean; evidence_id: string } | null;
  verdict: Verdict; verdict_by: string;               // "groq/openai/gpt-oss-120b" or "rules"
  rationale: string; cited: string[];
  actual_quote: { text: string; speaker: string; call: string; source_url: string } | null;
  notes: string[];
}
```

