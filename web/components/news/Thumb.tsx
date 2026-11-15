"use client";

// Company identity and the small data visuals on a row.
// - Logo: the company's own logo (saved once by scripts/fetch_logos.py and served from FINN's
//   own domain) on a light tile. No logo file, or one that fails to load: the monogram on a
//   tile tinted by the company's sector. Logos identify the company; nothing implies affiliation.
// - ResultsGlyph: the headline figure's last three quarters as tiny bars (reported figures: ink).
// - PriceGlyph: the closes into a price alert as a tiny line (a price move: green or red).
import { useState } from "react";
import { croreShort } from "@/lib/format";
import { resultsHeadlines, sparkValues } from "@/lib/present";
import type { Card, InboxData, PriceAlert } from "@/lib/types";
import s from "./thumb.module.css";

const DROP = new Set(["ltd", "limited", "the", "&", "and", "of", "india"]);

export function monogram(name: string): string {
  const words = name.replace(/\(.*?\)/g, " ").split(/[\s.-]+/).filter((w) => w && !DROP.has(w.toLowerCase()));
  if (!words.length) return "?";
  if (words.length === 1) return words[0].slice(0, 2).replace(/^./, (c) => c.toUpperCase());
  return (words[0][0] + words[1][0]).toUpperCase();
}

export function hueFor(sector: string | null | undefined, hues: Record<string, number>): number | null {
  if (!sector) return null;
  const family = sector.split(" - ")[0].trim();
  return hues[family] ?? hues[sector] ?? null;
}

export function Logo({ symbol, name, sector, hues, logos, size = 44 }: { symbol: string; name: string; sector?: string | null; hues: Record<string, number>; logos: string[]; size?: 36 | 44 | 52 }) {
  const [failed, setFailed] = useState(false);
  const has = logos.includes(symbol) && !failed;
  if (has) {
    const inner = size - 2 * Math.round(size * 0.14);
    return (
      <span className={s.tile} data-thumb="logo" data-size={size}>
        <img
          src={`/logos/${encodeURIComponent(symbol)}.png`}
          alt={name}
          width={inner}
          height={inner}
          loading="lazy"
          decoding="async"
          onError={() => setFailed(true)}
          // a file that failed before the page hydrated never fires onError: check on mount
          ref={(img) => {
            if (img && img.complete && img.naturalWidth === 0) setFailed(true);
          }}
        />
      </span>
    );
  }
  const hue = hueFor(sector, hues);
  return (
    <span className={s.tile} data-thumb="mono" data-size={size} data-tinted={hue !== null || undefined} style={hue !== null ? ({ "--h": hue } as React.CSSProperties) : undefined} role="img" aria-label={name}>
      <span aria-hidden="true">{monogram(name)}</span>
    </span>
  );
}

export function CardThumb({ card, data }: { card: Card; data: InboxData }) {
  const sym = card.lead.symbol;
  const co = data.companies[sym];
  return <Logo symbol={sym} name={co?.name ?? sym} sector={co?.sector} hues={data.sector_hues} logos={data.logos} />;
}

export function AlertThumb({ alert, data }: { alert: PriceAlert; data: InboxData }) {
  const co = data.companies[alert.symbol];
  return <Logo symbol={alert.symbol} name={co?.name ?? alert.name ?? alert.symbol} sector={co?.sector} hues={data.sector_hues} logos={data.logos} />;
}

/** Tiny bars for a results card's headline figure, or nothing for other cards. */
export function ResultsGlyph({ card, data }: { card: Card; data: InboxData }) {
  const res = card.results_symbol ? data.results[card.results_symbol] : undefined;
  const head = resultsHeadlines(card, data)[0];
  if (!res || !head) return null;
  const m = res.metrics.find((x) => x.label === head.label);
  const vals = m ? [m.year_ago, m.previous, m.current] : [];
  if (!m || !vals.every((v) => v !== null)) return null;
  const values = vals as number[];
  const periods = [res.periods.year_ago, res.periods.previous, res.periods.current];
  const W = 26, H = 14, gap = 3;
  const max = Math.max(...values.map(Math.abs), 1);
  const hasNeg = values.some((v) => v < 0);
  const zero = hasNeg ? H / 2 : H;
  const scale = (hasNeg ? H / 2 : H) / max;
  const bw = (W - 2 * gap) / 3;
  return (
    <span className={s.glyph} role="img" aria-label={`${m.label}: ${values.map((v, i) => `${croreShort(v)} in ${periods[i]}`).join(", ")}`}>
      <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} aria-hidden="true">
        {values.map((v, i) => {
          const h = Math.max(1.5, Math.abs(v) * scale);
          return <rect key={i} x={i * (bw + gap)} y={v >= 0 ? zero - h : zero} width={bw} height={h} rx="1" fill={i === 2 ? "var(--fg)" : "var(--fg-2)"} opacity={i === 2 ? 1 : 0.45} />;
        })}
      </svg>
      <span className={s.glyphLabel}>{m.label}</span>
    </span>
  );
}

/** A tiny line of the closes into a price alert. */
export function PriceGlyph({ alert, data }: { alert: PriceAlert; data: InboxData }) {
  const vals = sparkValues(data.prices[alert.symbol], alert.date, Math.max(data.spark_sessions, 7));
  if (vals.length < 3) return null;
  const W = 40, H = 14, pad = 2;
  const lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1;
  const pts = vals.map((v, i) => [pad + (i * (W - 2 * pad)) / (vals.length - 1), pad + (H - 2 * pad) * (1 - (v - lo) / span)]);
  const up = (alert.pct_change ?? 0) >= 0;
  const c = up ? "var(--pos)" : "var(--neg)";
  return (
    <span className={s.glyph} role="img" aria-label={`Closing prices for ${vals.length} sessions into ${alert.date}`}>
      <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} aria-hidden="true">
        <polyline points={pts.map((p) => p.map((n) => n.toFixed(1)).join(",")).join(" ")} fill="none" stroke={c} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
        <circle cx={pts[pts.length - 1][0]} cy={pts[pts.length - 1][1]} r="1.75" fill={c} />
      </svg>
    </span>
  );
}
