// Build-time loader for research files (data/seed/research/SYMBOL.json, written by
// scripts/build_research.py). Server only. Missing files are an honest "not run yet".

import fs from "node:fs";
import path from "node:path";
import YAML from "yaml";

const ROOT = process.env.FINN_ROOT ? path.resolve(process.env.FINN_ROOT) : path.resolve(process.cwd(), "..");

export type Verdict = "Delivered" | "Missed" | "Pending" | "Goalposts moved" | "Unverified";

export interface Actual {
  label: string;
  value: number;
  unit: string;
  period: string;
  quarters: string[];
  complete: boolean;
  source: string;
  url: string | null;
}

export interface LedgerEntry {
  id: string;
  metric: string;
  metric_label: string;
  metric_text: string;
  period: string;
  period_status: string;
  target: { text: string | null; low: number | null; high: number | null; unit: string | null; basis: string };
  revised: boolean;
  revision_direction: string | null;
  revision_path: string | null;
  statements: { id: string; call: string; call_label?: string | null; fiscal: string | null; speaker: string; quote: string;
                target_text: string | null; basis: string; quote_score: number; source_url: string }[];
  evidence: ({ id: string; kind: "screener" } & Actual | { id: string; kind: "transcript"; call: string; speaker: string; text: string; source_url: string })[];
  check: { comparable: boolean; position: string | null; actual: number; complete: boolean } | null;
  verdict: Verdict;
  verdict_by: string;
  rationale: string;
  actual_quote: { text: string; speaker: string; call: string; source_url: string } | null;
  chart: { unit: string; guides: { call: string; fiscal: string | null; low: number; high: number }[];
           actual: { value: number; kind: "screener" | "stated"; label: string; complete: boolean } | null } | null;
  notes: string[];
}

export interface QuarterRow {
  period: string; fiscal: string; revenue: number | null; revenue_yoy: number | null; net_profit: number | null;
  net_profit_yoy: number | null; ebitda_margin?: number | null; ebit_margin?: number | null; gross_npa_pct?: number | null;
}

export interface ResearchDoc {
  symbol: string;
  name: string;
  generated_at: string;
  status: "ok" | "no_transcripts" | "no_promises" | "numbers_only" | "failed";
  error?: string;
  notes: string[];
  numbers: {
    basis: string; layout: "standard" | "lender"; unit: string; latest_quarter: string | null; latest_fiscal: string | null;
    quarters: QuarterRow[];
    fiscal_year_to_date: { period: string; metrics: Record<string, Actual | null> } | null;
    source: { name: string; url: string | null };
  } | null;
  transcripts: { call: string; kind?: string; label?: string; fiscal: string | null; url: string; error: string | null;
                 passages: number; sent: number; promises: number }[];
  ledger: LedgerEntry[];
  track_record?: { text: string; counts: Record<Verdict, number>; checkable: number; revised: number; promises: number };
  dropped: { call: string; quote: string; reason: string }[];
  models?: string[];
}

export interface CompanyEntry {
  symbol: string;
  name: string;
  sector: string | null;
  focus: string | null;
  doc: ResearchDoc | null;
}

function outputDir(): string {
  const cfg = YAML.parse(fs.readFileSync(path.join(/*turbopackIgnore: true*/ ROOT, "config", "research.yaml"), "utf8")) as { output_dir?: string };
  return path.join(/*turbopackIgnore: true*/ ROOT, cfg.output_dir ?? "data/seed/research");
}

export function loadResearch(symbol: string): ResearchDoc | null {
  const file = path.join(/*turbopackIgnore: true*/ outputDir(), `${symbol}.json`);
  if (!fs.existsSync(file)) return null;
  return JSON.parse(fs.readFileSync(file, "utf8")) as ResearchDoc;
}

/** Every company the app knows (portfolio from the manifest) plus any ticker with a research file. */
export function listCompanies(): CompanyEntry[] {
  const manifest = JSON.parse(fs.readFileSync(path.join(/*turbopackIgnore: true*/ ROOT, "data", "seed", "manifest.json"), "utf8")) as {
    companies: { symbol: string; name: string; sector: string | null; research_focus: string | null }[];
  };
  const out = new Map<string, CompanyEntry>();
  for (const c of manifest.companies) {
    out.set(c.symbol, { symbol: c.symbol, name: c.name, sector: c.sector, focus: c.research_focus, doc: null });
  }
  const dir = outputDir();
  const files = fs.existsSync(dir) ? fs.readdirSync(dir).filter((f) => f.endsWith(".json")) : [];
  for (const f of files) {
    const symbol = f.replace(/\.json$/, "");
    const entry = out.get(symbol) ?? { symbol, name: symbol, sector: null, focus: null, doc: null };
    entry.doc = loadResearch(symbol);
    if (entry.doc?.name) entry.name = entry.doc.name;
    out.set(symbol, entry);
  }
  return [...out.values()];
}
