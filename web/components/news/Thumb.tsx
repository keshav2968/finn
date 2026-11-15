// A news card's thumbnail, drawn from FINN's own data (no photos, logos or external images):
// - results: the headline figure's last three quarters as bars (reported figures: ink);
// - price alert: the closing prices into the alert as a small line (a price move: green/red);
// - anything else: the company's monogram on a tile tinted by its sector.
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

function hueFor(sector: string | null | undefined, hues: Record<string, number>): number | null {
  if (!sector) return null;
  const family = sector.split(" - ")[0].trim();
  return hues[family] ?? hues[sector] ?? null;
}

export function CardThumb({ card, data }: { card: Card; data: InboxData }) {
  const res = card.results_symbol ? data.results[card.results_symbol] : undefined;
  const head = resultsHeadlines(card, data)[0];
  if (res && head) {
    const m = res.metrics.find((x) => x.label === head.label);
    const vals = m ? [m.year_ago, m.previous, m.current] : [];
    if (m && vals.every((v) => v !== null)) return <Bars label={m.label} values={vals as number[]} periods={[res.periods.year_ago, res.periods.previous, res.periods.current]} />;
  }
  const co = data.companies[card.lead.symbol];
  return <Monogram name={co?.name ?? card.lead.symbol} hue={hueFor(co?.sector, data.sector_hues)} />;
}

export function AlertThumb({ alert, data }: { alert: PriceAlert; data: InboxData }) {
  const vals = sparkValues(data.prices[alert.symbol], alert.date, Math.max(data.spark_sessions, 7));
  if (vals.length < 3) {
    const co = data.companies[alert.symbol];
    return <Monogram name={co?.name ?? alert.symbol} hue={hueFor(co?.sector, data.sector_hues)} />;
  }
  const W = 44, H = 44, pad = 7;
  const lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1;
  const pts = vals.map((v, i) => [pad + (i * (W - 2 * pad)) / (vals.length - 1), pad + (H - 2 * pad) * (1 - (v - lo) / span)]);
  const up = (alert.pct_change ?? 0) >= 0;
  return (
    <span className={s.tile} data-thumb="spark" role="img" aria-label={`Closing prices into ${alert.date}`}>
      <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} aria-hidden="true">
        <polyline points={pts.map((p) => p.map((n) => n.toFixed(1)).join(",")).join(" ")} fill="none" stroke={up ? "var(--pos)" : "var(--neg)"} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        <circle cx={pts[pts.length - 1][0]} cy={pts[pts.length - 1][1]} r="2.5" fill={up ? "var(--pos)" : "var(--neg)"} />
      </svg>
    </span>
  );
}

function Monogram({ name, hue }: { name: string; hue: number | null }) {
  return (
    <span className={s.tile} data-thumb="mono" data-tinted={hue !== null || undefined} style={hue !== null ? ({ "--h": hue } as React.CSSProperties) : undefined} aria-hidden="true">
      {monogram(name)}
    </span>
  );
}

function Bars({ label, values, periods }: { label: string; values: number[]; periods: string[] }) {
  const W = 44, H = 44, padX = 8, padY = 8, gap = 4;
  const max = Math.max(...values.map(Math.abs), 1);
  const hasNeg = values.some((v) => v < 0);
  const zero = hasNeg ? padY + (H - 2 * padY) / 2 : H - padY;
  const scale = (hasNeg ? (H - 2 * padY) / 2 : H - 2 * padY) / max;
  const bw = (W - 2 * padX - 2 * gap) / 3;
  return (
    <span
      className={s.tile}
      data-thumb="bars"
      role="img"
      aria-label={`${label}: ${values.map((v, i) => `${croreShort(v)} in ${periods[i]}`).join(", ")}`}
    >
      <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} aria-hidden="true">
        <line x1={padX - 2} x2={W - padX + 2} y1={zero} y2={zero} stroke="var(--muted)" strokeOpacity="0.6" />
        {values.map((v, i) => {
          const h = Math.max(1.5, Math.abs(v) * scale);
          return <rect key={i} x={padX + i * (bw + gap)} y={v >= 0 ? zero - h : zero} width={bw} height={h} rx="1.5" fill={i === 2 ? "var(--fg)" : "var(--fg-2)"} opacity={i === 2 ? 1 : 0.45} />;
        })}
      </svg>
    </span>
  );
}
